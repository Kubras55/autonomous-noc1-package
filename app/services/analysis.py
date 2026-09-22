import json
import re

import httpx

from app.config import get_settings
from app.models import Incident


def apply_output_guardrails(incident: Incident, data: dict) -> tuple[dict, bool]:
    """Keep small local-model output actionable and Turkish for known telemetry."""
    text = f"{incident.title} {incident.description}".lower()
    guarded = False

    if incident.source == "gns3-vlan-monitor":
        guarded = True
        if "core path" in text or "upstream" in text:
            data.update({
                "summary": f"{incident.affected_service} gateway erişimi başarılı, core yolu erişilemez",
                "root_cause": "R1/R2 upstream yönlendirme veya statik dönüş rotası sorunu",
                "confidence_score": 0.92,
                "recommended_action": "inspect_upstream_static_routes",
                "risk": "MEDIUM",
            })
        else:
            data.update({
                "summary": f"{incident.affected_service} gateway erişilemez",
                "root_cause": "VLAN, 802.1Q alt arayüzü veya access port yapılandırma sorunu",
                "confidence_score": 0.92,
                "recommended_action": "inspect_vlan_gateway_and_dot1q",
                "risk": "HIGH",
            })

    if incident.source == "nms-syslog":
        guarded = True
        if "ospf" in text:
            data.update({
                "summary": f"{incident.affected_service} OSPF komşuluk değişikliği algılandı",
                "root_cause": "OSPF komşuluğu arayüz veya bağlantı kesintisi nedeniyle düştü",
                "confidence_score": 0.96,
                "recommended_action": "inspect_ospf_neighbor_and_redundant_path",
                "risk": "MEDIUM",
            })
        else:
            data.update({
                "summary": f"{incident.affected_service} router arayüzü down durumuna geçti",
                "root_cause": "Router arayüzü kapandı veya fiziksel bağlantı kesildi",
                "confidence_score": 0.97,
                "recommended_action": "inspect_interface_and_ospf_impact",
                "risk": "MEDIUM",
            })

    # A GNS3 node-down alert has one intentionally narrow, low-impact action:
    # start only that stopped node via the GNS3 API after operator approval.
    if "gns3" in text and ("down" in text or "node is stopped" in text):
        guarded = True
        data.update({
            "summary": f"{incident.affected_service} GNS3 düğümü durdurulmuş",
            "root_cause": "GNS3 emülatör düğümü çalışmıyor",
            "confidence_score": 0.98,
            "recommended_action": "start_gns3_node_and_verify_links",
            "risk": "MEDIUM",
        })
    has_cjk = any(
        isinstance(value, str) and re.search(r"[\u3400-\u9fff]", value)
        for value in data.values()
    )
    if has_cjk and not guarded:
        guarded = True
        data.update({
            "summary": f"{incident.title}: yerel model yanıtı dil denetimine takıldı",
            "root_cause": "Yetersiz veya dil politikasına uymayan model çıktısı",
            "confidence_score": 0.55,
            "recommended_action": "collect_more_evidence",
            "risk": "LOW",
        })

    return data, guarded


def rule_based_analysis(incident: Incident) -> dict:
    text = f"{incident.title} {incident.description} {incident.affected_service}".lower()
    rules = [
        (("gns3", "node is stopped"), "GNS3 ağ düğümü durdurulmuş veya emülatör süreci çalışmıyor", 0.98, "start_gns3_node_and_verify_links", "MEDIUM"),
        (("vlan", "dot1q", "802.1q"), "VLAN/802.1Q yapılandırma uyuşmazlığı", 0.92, "rollback_vlan_config", "HIGH"),
        (("packet loss", "paket kaybı"), "Bağlantıda paket kaybı veya kuyruk taşması", 0.88, "inspect_link_and_qos", "MEDIUM"),
        (("latency", "gecikme"), "Yüksek ağ gecikmesi", 0.84, "inspect_path_latency", "LOW"),
        (("bng", "subscriber"), "BNG abone erişim veya oturum sorunu", 0.86, "inspect_bng_sessions", "HIGH"),
        (("down", "ulaşılamıyor"), "Servis veya ağ düğümü erişilemiyor", 0.90, "check_service_and_route", "MEDIUM"),
    ]
    for words, cause, score, action, risk in rules:
        if any(word in text for word in words):
            break
    else:
        cause, score, action, risk = "Yetersiz telemetri; ek metrik ve log gerekli", 0.55, "collect_more_evidence", "LOW"
    return {"root_cause": cause, "confidence_score": score, "recommended_action": action, "risk": risk}


def analyze_incident(incident: Incident) -> dict:
    settings = get_settings()
    fallback = rule_based_analysis(incident)
    if settings.llm_provider == "ollama":
        prompt = {
            "role": "Autonomous NOC incident analyst",
            "language": "Turkish",
            "incident": {
                "title": incident.title,
                "description": incident.description,
                "severity": incident.severity.value,
                "source": incident.source,
                "affected_service": incident.affected_service,
            },
            "rule_evidence": fallback,
            "instructions": [
                "Use only supplied evidence; do not invent metrics, logs, or commands.",
                "Explain the likely root cause for a junior network operator.",
                "Return JSON only with summary, root_cause, confidence_score, recommended_action, risk.",
                "confidence_score must be between 0 and 1; risk must be LOW, MEDIUM, or HIGH.",
            ],
        }
        try:
            response = httpx.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "stream": False,
                    "format": "json",
                    "think": False,
                    "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
                    "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 300},
                },
                timeout=180,
            )
            response.raise_for_status()
            data = json.loads(response.json()["message"]["content"])
            data, guarded = apply_output_guardrails(incident, data)
            suffix = "+guardrail" if guarded else ""
            return {"provider": f"ollama/{settings.ollama_model}{suffix}", **data}
        except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError, ValueError):
            return {"provider": "rule-based-ollama-fallback", "summary": f"Yerel LLM kullanılamadı: {fallback['root_cause']}", **fallback}

    if settings.llm_provider != "openai" or not settings.openai_api_key:
        return {"provider": "rule-based", "summary": f"{incident.title}: {fallback['root_cause']}", **fallback}

    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = {
        "incident": {"title": incident.title, "description": incident.description, "severity": incident.severity.value,
                     "source": incident.source, "affected_service": incident.affected_service},
        "task": "Return JSON with summary, root_cause, confidence_score (0-1), recommended_action, risk (LOW/MEDIUM/HIGH). Do not invent evidence."
    }
    response = client.responses.create(model=settings.llm_model, input=json.dumps(prompt, ensure_ascii=False))
    try:
        data = json.loads(response.output_text)
        return {"provider": "openai", **data}
    except (json.JSONDecodeError, TypeError):
        return {"provider": "rule-based-fallback", "summary": f"LLM yanıtı ayrıştırılamadı: {fallback['root_cause']}", **fallback}
