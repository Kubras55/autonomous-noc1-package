import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = APP_DIR / "templates" / "operator_console.html"
STATIC_DIR = APP_DIR / "static"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001").rstrip("/")
GNS3_URL = os.getenv("GNS3_URL", "http://localhost:3081").rstrip("/")
GNS3_PROJECT = os.getenv("GNS3_PROJECT", "Autonomous-NOC-Redundant-OSPF")
ALLOWED_ACTION = "start_gns3_node_and_verify_links"
SERVICE_NODE_MAP = {
    "subscriber-vlan-100": "R3-BNG",
    "subscriber-vlan-200": "R3-BNG",
    # Compatibility with incidents created by the earlier, non-redundant lab.
    "R1-CORE": "R1-CORE-1",
    "R2-EDGE": "R3-EDGE-1",
    "R3-BNG": "R5-BNG",
}
AUDIT_PATH = Path(os.getenv("AUDIT_PATH", "logs/remediation-audit.jsonl"))
ANALYSIS_CACHE: dict[str, dict] = {}

app = FastAPI(title="Autonomous NOC Operator Console", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def disable_browser_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith(("/api/", "/static/")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


class Decision(BaseModel):
    approved: bool
    operator: str = "local-operator"
    note: str = ""


class ReviewDecision(BaseModel):
    operator: str = "local-operator"
    note: str = ""


def write_audit(**event):
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    with AUDIT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


async def get_json(client: httpx.AsyncClient, url: str):
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def run_read_only_ios_commands(node: dict, commands: list[str]) -> str:
    """Run show commands on an IOS console without entering configuration mode."""
    if node.get("status") != "started":
        raise RuntimeError(f"{node['name']} çalışmıyor (durum: {node.get('status')})")
    if not node.get("console"):
        raise RuntimeError(f"{node['name']} konsol portu bulunamadı")

    host = node.get("console_host") or "127.0.0.1"
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, int(node["console"])), timeout=5
    )
    try:
        writer.write(b"\r\n")
        await writer.drain()
        await asyncio.sleep(0.4)
        for command in ["terminal length 0", *commands]:
            writer.write(command.encode("ascii") + b"\r\n")
            await writer.drain()
            await asyncio.sleep(0.7)

        chunks = []
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(65535), timeout=0.5)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="ignore")
    finally:
        writer.close()
        await writer.wait_closed()


def interface_is_up(output: str, interface: str) -> bool:
    pattern = rf"(?mi)^{re.escape(interface)}\s+\S+\s+YES\s+\S+\s+up\s+up\s*$"
    return re.search(pattern, output) is not None


def diagnostic_result(name: str, passed: bool, evidence: str, device: str) -> dict:
    return {
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "evidence": evidence,
        "device": device,
    }


def incident_is_upstream(incident: dict) -> bool:
    evidence = f"{incident.get('title', '')} {incident.get('description', '')}".lower()
    return "core path" in evidence or "upstream" in evidence


def target_node_for_incident(incident: dict) -> str:
    if incident["affected_service"] in SERVICE_NODE_MAP and incident_is_upstream(incident):
        return "R1-CORE-1"
    return SERVICE_NODE_MAP.get(incident["affected_service"], incident["affected_service"])


async def load_context(incident_id: str, refresh_analysis: bool = False):
    async with httpx.AsyncClient(timeout=240) as client:
        try:
            incident, projects = await asyncio.gather(
                get_json(client, f"{BACKEND_URL}/incidents/{incident_id}"),
                get_json(client, f"{GNS3_URL}/v2/projects"),
            )
            analysis = ANALYSIS_CACHE.get(incident_id)
            if refresh_analysis or analysis is None:
                analysis = await get_json(client, f"{BACKEND_URL}/incidents/{incident_id}/ai-analysis")
                ANALYSIS_CACHE[incident_id] = analysis

            target_node = target_node_for_incident(incident)
            preferred = next((item for item in projects if item["name"] == GNS3_PROJECT), None)
            if preferred is None:
                raise HTTPException(
                    404,
                    f"Ayarlanan GNS3 projesi bulunamadı: {GNS3_PROJECT}",
                )

            # Never fall back to another project. A device with the same name can
            # exist in an old lab and cause remediation to target the wrong node.
            nodes = await get_json(
                client,
                f"{GNS3_URL}/v2/projects/{preferred['project_id']}/nodes",
            )
            node = next((item for item in nodes if item["name"] == target_node), None)
            if node:
                return incident, analysis, preferred, node

            raise HTTPException(
                404,
                f"GNS3 düğümü bulunamadı: {target_node}. "
                "İlgili GNS3 projesinin açık olduğunu ve cihaz adının aynı yazıldığını kontrol edin.",
            )
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Bağlı servise erişilemedi: {exc}") from exc


def validate_analysis(analysis: dict):
    if analysis.get("recommended_action") != ALLOWED_ACTION:
        raise HTTPException(409, "Güvenlik engeli: önerilen işlem izin listesinde değil.")
    if analysis.get("risk") == "HIGH":
        raise HTTPException(409, "Güvenlik engeli: HIGH riskli işlem uygulanamaz.")


@app.get("/", response_class=HTMLResponse)
def operator_page():
    return HTMLResponse(TEMPLATE_PATH.read_text(encoding="utf-8"))


@app.get("/api/incidents")
async def incidents():
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            return await get_json(client, f"{BACKEND_URL}/incidents")
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Backend'e erişilemedi: {exc}") from exc


@app.get("/api/incidents/{incident_id}/events")
async def incident_timeline(incident_id: str):
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            return await get_json(client, f"{BACKEND_URL}/incidents/{incident_id}/events")
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Olay geçmişi alınamadı: {exc}") from exc


@app.get("/api/incidents/{incident_id}/plan")
async def remediation_plan(incident_id: str, refresh: bool = False):
    incident, analysis, project, node = await load_context(incident_id, refresh_analysis=refresh)
    # Subscriber VLAN and NMS incidents are diagnostic-only.  Router node-down
    # alerts are different: they may safely use the GNS3 Start API after approval.
    diagnostic_only = (
        incident["affected_service"].startswith("subscriber-vlan-")
        or incident.get("source") in {"nms-snmp", "nms-syslog"}
    )
    allowed = (
        not diagnostic_only
        and analysis.get("recommended_action") == ALLOWED_ACTION
        and analysis.get("risk") != "HIGH"
    )
    if incident.get("source") in {"nms-snmp", "nms-syslog"}:
        steps = [
            f"Etkilenen cihaz: {node['name']} (GNS3 durumu: {node.get('status', 'bilinmiyor')})",
            "NMS sunucusundan cihazın yönetim IP adresine ağ erişimi doğrulanacak.",
            "SNMP v2c sorgusu, NOC-RO community bilgisi ve UDP/161 erişimi kontrol edilecek.",
            "Cihazın arayüzleri ile OSPF komşulukları salt okunur komutlarla incelenecek.",
            "Syslog ve SNMP trap kayıtları aynı zaman aralığı için karşılaştırılacak.",
            "Otomatik yapılandırma değişikliği uygulanmayacak; sonuç operatör onayına sunulacak.",
        ]
    elif diagnostic_only:
        vlan = incident["affected_service"].rsplit("-", 1)[-1]
        if incident_is_upstream(incident):
            steps = [
                f"Etkilenen servis: VLAN {vlan} upstream/core erişimi",
                "Gateway başarılı olduğu için SW-ACCESS ve R3-BNG abone alt arayüzü sağlıklı kabul edilecek.",
                f"R1-CORE üzerinde 192.168.{vlan}.0/24 dönüş rotasının 10.0.0.2 next-hop adresine yöneldiği kontrol edilecek.",
                f"R2-EDGE üzerinde 192.168.{vlan}.0/24 rotasının 10.0.0.6 next-hop adresine yöneldiği kontrol edilecek.",
                "R3-BNG, R2-EDGE ve R1-CORE arasındaki /30 bağlantıların up/up durumu doğrulanacak.",
                "Bu olayda otomatik route değişikliği uygulanmayacak; plan yalnızca teşhis amaçlıdır.",
            ]
        else:
            steps = [
                f"Etkilenen servis: VLAN {vlan} abone erişimi",
                f"İlişkili GNS3 cihazı: {node['name']} (mevcut durum: {node.get('status', 'bilinmiyor')})",
                f"R3-BNG FastEthernet0/1.{vlan} alt arayüz durumu kontrol edilecek.",
                f"802.1Q VLAN {vlan} kapsüllemesi ve gateway IP yapılandırması doğrulanacak.",
                f"SW-ACCESS istemci portunun access VLAN {vlan} ve R3 bağlantısının dot1q olduğu kontrol edilecek.",
                "Bu olayda otomatik CLI komutu uygulanmayacak; plan yalnızca teşhis amaçlıdır.",
            ]
    else:
        steps = [
            f"Hedef GNS3 projesi: {project['name']}",
            f"Hedef cihaz: {node['name']} (mevcut durum: {node.get('status', 'bilinmiyor')})",
            "Cihaz durmuşsa yalnızca GNS3 Start API çağrısı yapılacak.",
            "En fazla 20 saniye status=started sonucu doğrulanacak.",
            "IP, VLAN, route ve router yapılandırmaları değiştirilmeyecek.",
            "Hiçbir cihaz silinmeyecek ve diğer düğümlere dokunulmayacak.",
        ]
    return {
        "incident": incident,
        "analysis": analysis,
        "allowed": allowed,
        "project": project["name"],
        "node": node["name"],
        "current_status": node.get("status", "bilinmiyor"),
        "mode": "diagnostic" if diagnostic_only else "remediation",
        "steps": steps,
    }


@app.get("/api/incidents/{incident_id}/diagnostics")
async def run_diagnostics(incident_id: str):
    incident, _, project, target_node = await load_context(incident_id)
    if incident.get("source") in {"nms-snmp", "nms-syslog"}:
        gns3_started = target_node.get("status") == "started"
        checks = [
            diagnostic_result(
                "GNS3 düğüm durumu",
                gns3_started,
                f"{target_node['name']} durumu: {target_node.get('status', 'bilinmiyor')}",
                target_node["name"],
            )
        ]

        if gns3_started:
            try:
                output = await run_read_only_ios_commands(
                    target_node,
                    [
                        "show ip interface brief",
                        "show ip ospf neighbor",
                        "show ip route ospf",
                        "show running-config | include snmp-server",
                    ],
                )
            except (OSError, asyncio.TimeoutError, RuntimeError) as exc:
                raise HTTPException(
                    502,
                    f"{target_node['name']} konsol teşhisi çalıştırılamadı: {exc}",
                ) from exc

            up_up_count = len(re.findall(r"(?mi)^\S+\s+\S+\s+YES\s+\S+\s+up\s+up\s*$", output))
            ospf_full_count = len(re.findall(r"\bFULL(?:/|-)", output, re.IGNORECASE))
            ospf_route_count = len(re.findall(r"(?mi)^O(?:\s|\*)", output))
            snmp_configured = (
                "snmp-server community NOC-RO RO".lower() in output.lower()
            )
            checks.extend([
                diagnostic_result(
                    "Aktif router arayüzleri",
                    up_up_count > 0,
                    f"{up_up_count} arayüz up/up durumda",
                    target_node["name"],
                ),
                diagnostic_result(
                    "OSPF komşulukları",
                    ospf_full_count >= 2,
                    f"{ospf_full_count} OSPF komşuluğu FULL durumda; yedeklilik için en az 2 bekleniyor",
                    target_node["name"],
                ),
                diagnostic_result(
                    "OSPF öğrenilmiş rotalar",
                    ospf_route_count > 0,
                    f"Yönlendirme tablosunda {ospf_route_count} OSPF rota satırı bulundu",
                    target_node["name"],
                ),
                diagnostic_result(
                    "SNMP salt okunur yapılandırması",
                    snmp_configured,
                    "NOC-RO community yapılandırması " + ("bulundu" if snmp_configured else "bulunamadı"),
                    target_node["name"],
                ),
            ])

        failed = [check for check in checks if check["status"] == "FAIL"]
        conclusion = (
            f"Öncelikli arıza adayı: {failed[0]['name']} — {failed[0]['evidence']}"
            if failed else
            "Router ve OSPF kontrolleri başarılı; NMS erişim yolu ile UDP/161 trafiği ayrıca kontrol edilmeli."
        )
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{BACKEND_URL}/incidents/{incident_id}/events",
                json={
                    "event_type": "DIAGNOSTIC_RUN",
                    "source": "operator-console",
                    "message": "SNMP/OSPF salt okunur canlı teşhisi tamamlandı",
                    "details": {"checks": checks, "conclusion": conclusion},
                },
            )
            response.raise_for_status()
        return {
            "read_only": True,
            "checks": checks,
            "conclusion": conclusion,
            "executed_commands": [
                "show ip interface brief",
                "show ip ospf neighbor",
                "show ip route ospf",
                "show running-config | include snmp-server",
            ] if gns3_started else [],
        }

    if incident["affected_service"] not in SERVICE_NODE_MAP or not incident_is_upstream(incident):
        raise HTTPException(409, "Bu olay türü için canlı teşhis henüz tanımlı değil.")

    vlan = incident["affected_service"].rsplit("-", 1)[-1]
    prefix = f"192.168.{vlan}.0"
    async with httpx.AsyncClient(timeout=20) as client:
        nodes = await get_json(client, f"{GNS3_URL}/v2/projects/{project['project_id']}/nodes")
    node_map = {node["name"]: node for node in nodes}
    required = ["R1-CORE", "R2-EDGE", "R3-BNG"]
    missing = [name for name in required if name not in node_map]
    if missing:
        raise HTTPException(404, f"Teşhis cihazları bulunamadı: {', '.join(missing)}")

    try:
        r1_output, r2_output, r3_output = await asyncio.gather(
            run_read_only_ios_commands(node_map["R1-CORE"], [
                f"show ip route {prefix}", "show ip interface brief"
            ]),
            run_read_only_ios_commands(node_map["R2-EDGE"], [
                f"show ip route {prefix}", "show ip interface brief"
            ]),
            run_read_only_ios_commands(node_map["R3-BNG"], ["show ip interface brief"]),
        )
    except (OSError, asyncio.TimeoutError, RuntimeError) as exc:
        raise HTTPException(502, f"GNS3 konsol teşhisi çalıştırılamadı: {exc}") from exc

    r1_route_ok = f"Routing entry for {prefix}/24" in r1_output and "10.0.0.2" in r1_output
    r2_route_ok = f"Routing entry for {prefix}/24" in r2_output and "10.0.0.6" in r2_output
    r1_link_ok = interface_is_up(r1_output, "FastEthernet0/0")
    r2_links_ok = (
        interface_is_up(r2_output, "FastEthernet0/0")
        and interface_is_up(r2_output, "FastEthernet0/1")
    )
    r3_links_ok = (
        interface_is_up(r3_output, "FastEthernet0/0")
        and interface_is_up(r3_output, f"FastEthernet0/1.{vlan}")
    )
    checks = [
        diagnostic_result(
            "R1 dönüş rotası", r1_route_ok,
            f"{prefix}/24 → 10.0.0.2 " + ("bulundu" if r1_route_ok else "bulunamadı veya next-hop yanlış"),
            "R1-CORE",
        ),
        diagnostic_result(
            "R2 abone rotası", r2_route_ok,
            f"{prefix}/24 → 10.0.0.6 " + ("bulundu" if r2_route_ok else "bulunamadı veya next-hop yanlış"),
            "R2-EDGE",
        ),
        diagnostic_result(
            "R1–R2 bağlantısı", r1_link_ok and r2_links_ok,
            "R1 Fa0/0 ile R2 Fa0/0/Fa0/1 arayüzleri " + ("up/up" if r1_link_ok and r2_links_ok else "tamamı up/up değil"),
            "R1-CORE / R2-EDGE",
        ),
        diagnostic_result(
            "R3–R2 ve VLAN alt arayüzü", r3_links_ok,
            f"R3 Fa0/0 ve Fa0/1.{vlan} " + ("up/up" if r3_links_ok else "tamamı up/up değil"),
            "R3-BNG",
        ),
    ]
    failed = [check for check in checks if check["status"] == "FAIL"]
    conclusion = (
        f"Kesin arıza adayı: {failed[0]['device']} — {failed[0]['name']}"
        if failed else
        "Router kontrolleri başarılı; olay düzelmiş veya istemci testi yeniden doğrulanmalı."
    )
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{BACKEND_URL}/incidents/{incident_id}/events",
            json={
                "event_type": "DIAGNOSTIC_RUN",
                "source": "operator-console",
                "message": "Salt okunur GNS3 canlı teşhisi tamamlandı",
                "details": {"checks": checks, "conclusion": conclusion},
            },
        )
        response.raise_for_status()
    return {
        "read_only": True,
        "vlan": vlan,
        "checks": checks,
        "conclusion": conclusion,
        "executed_commands": ["show ip route", "show ip interface brief"],
    }


@app.post("/api/incidents/{incident_id}/decision")
async def decide(incident_id: str, decision: Decision):
    incident, analysis, project, node = await load_context(incident_id)
    common = {
        "incident_id": incident_id,
        "operator": decision.operator.strip() or "local-operator",
        "note": decision.note.strip(),
        "action": analysis.get("recommended_action"),
        "risk": analysis.get("risk"),
        "node": node["name"],
    }
    if not decision.approved:
        write_audit(**common, approved=False, outcome="rejected", executed=False)
        return {"status": "rejected", "executed": False, "message": "Müdahale reddedildi; değişiklik yapılmadı."}

    try:
        validate_analysis(analysis)
    except HTTPException:
        write_audit(**common, approved=True, outcome="blocked", executed=False)
        raise

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            executed = node.get("status") != "started"
            if executed:
                response = await client.post(
                    f"{GNS3_URL}/v2/projects/{project['project_id']}/nodes/{node['node_id']}/start"
                )
                response.raise_for_status()
            for _ in range(10):
                await asyncio.sleep(2)
                current = await get_json(
                    client,
                    f"{GNS3_URL}/v2/projects/{project['project_id']}/nodes/{node['node_id']}",
                )
                if current["status"] == "started":
                    write_audit(**common, approved=True, outcome="completed", executed=executed)
                    return {
                        "status": "completed",
                        "executed": executed,
                        "node": node["name"],
                        "verified_status": "started",
                    }
        except httpx.HTTPError as exc:
            write_audit(**common, approved=True, outcome="failed", executed=False, error=str(exc))
            raise HTTPException(502, f"GNS3 müdahalesi başarısız: {exc}") from exc

    write_audit(**common, approved=True, outcome="verification_timeout", executed=executed)
    raise HTTPException(504, f"Müdahale doğrulanamadı: {incident['affected_service']}")


@app.post("/api/incidents/{incident_id}/investigate")
async def operator_investigate(incident_id: str, decision: ReviewDecision):
    operator = decision.operator.strip() or "local-operator"
    note = decision.note.strip()
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            incident = await get_json(client, f"{BACKEND_URL}/incidents/{incident_id}")
            if incident["status"] != "open":
                raise HTTPException(409, "Yalnızca aktif olaylar incelemeye alınabilir.")
            event_response = await client.post(
                f"{BACKEND_URL}/incidents/{incident_id}/events",
                json={
                    "event_type": "OPERATOR_REVIEW",
                    "source": operator,
                    "message": "Operatör olayı incelemeye aldı",
                    "details": {"note": note},
                },
            )
            event_response.raise_for_status()
            response = await client.patch(
                f"{BACKEND_URL}/incidents/{incident_id}/status",
                json={"status": "investigating"},
            )
            response.raise_for_status()
            updated = response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Incident incelemeye alınamadı: {exc}") from exc

    write_audit(
        incident_id=incident_id,
        operator=operator,
        note=note,
        action="operator_started_investigation",
        risk="N/A",
        node=incident["affected_service"],
        approved=True,
        outcome="investigating",
        executed=False,
    )
    return {
        "status": updated["status"],
        "message": "Olay incelemeye alındı. Doğrulama tamamlandığında çözüldü olarak kapatabilirsiniz.",
    }


@app.post("/api/incidents/{incident_id}/resolve")
async def operator_resolve(incident_id: str, decision: ReviewDecision):
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            incident = await get_json(client, f"{BACKEND_URL}/incidents/{incident_id}")
            if incident["status"] != "investigating":
                raise HTTPException(
                    409,
                    "Olay yalnızca teknik iyileşme sonrası inceleme beklerken kapatılabilir.",
                )
            review_response = await client.post(
                f"{BACKEND_URL}/incidents/{incident_id}/events",
                json={
                    "event_type": "OPERATOR_REVIEW",
                    "source": decision.operator.strip() or "local-operator",
                    "message": "Operatör olayı inceledi ve çözümü doğruladı",
                    "details": {"note": decision.note.strip()},
                },
            )
            review_response.raise_for_status()
            response = await client.patch(
                f"{BACKEND_URL}/incidents/{incident_id}/status",
                json={"status": "resolved"},
            )
            response.raise_for_status()
            updated = response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Incident durumu güncellenemedi: {exc}") from exc

    write_audit(
        incident_id=incident_id,
        operator=decision.operator.strip() or "local-operator",
        note=decision.note.strip(),
        action="operator_verified_resolution",
        risk="N/A",
        node=incident["affected_service"],
        approved=True,
        outcome="resolved_by_operator",
        executed=False,
    )
    return {
        "status": updated["status"],
        "message": "Olay operatör incelemesiyle çözüldü olarak kapatıldı.",
    }


@app.get("/api/audit")
def audit_events():
    if not AUDIT_PATH.exists():
        return []
    lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-100:]
    return [json.loads(line) for line in reversed(lines) if line.strip()]
