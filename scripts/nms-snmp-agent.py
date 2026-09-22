"""Poll GNS3 routers with SNMP and forward availability alarms to Autonomous NOC."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request


SYS_NAME_OID = "1.3.6.1.2.1.1.5.0"
DEFAULT_TARGETS = (
    "R1-CORE-1=10.0.0.1,R2-CORE-2=10.0.0.2,"
    "R3-EDGE-1=10.0.0.21,R4-EDGE-2=10.0.0.25,R5-BNG=192.168.99.1"
)


def parse_targets(raw: str) -> dict[str, str]:
    targets: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        name, separator, address = item.partition("=")
        if not separator or not name.strip() or not address.strip():
            raise ValueError(f"Geçersiz hedef: {item!r}; NAME=IP biçimi kullanılmalı")
        targets[name.strip()] = address.strip()
    if not targets:
        raise ValueError("En az bir SNMP hedefi gerekli")
    return targets


def snmp_probe(address: str, community: str, timeout: int) -> tuple[bool, str]:
    command = [
        "snmpget",
        "-v2c",
        "-c",
        community,
        "-t",
        str(timeout),
        "-r",
        "0",
        address,
        SYS_NAME_OID,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout + 2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    detail = (result.stdout or result.stderr).strip()
    return result.returncode == 0, detail


def alert_payload(name: str, address: str, status: str, detail: str) -> dict:
    return {
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "SnmpNodeUnreachable",
                    "severity": "critical",
                    "service": name,
                    "instance": address,
                    "source": "nms-snmp",
                },
                "annotations": {
                    "summary": f"{name} SNMP ile erişilemiyor",
                    "description": (
                        f"NMS, {address} adresindeki {name} cihazından SNMP yanıtı alamadı. "
                        f"Son kontrol: {detail or 'yanıt yok'}"
                    ),
                },
                "fingerprint": f"nms-snmp-unreachable:{name}:{address}",
            }
        ]
    }


def send_alert(backend_url: str, payload: dict, timeout: int = 10) -> None:
    request = urllib.request.Request(
        f"{backend_url.rstrip('/')}/alerts/prometheus",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status >= 300:
            raise RuntimeError(f"Backend HTTP {response.status}")
        response.read()


def run(args: argparse.Namespace) -> None:
    targets = parse_targets(args.targets)
    failures = {name: 0 for name in targets}
    firing = {name: False for name in targets}

    while True:
        for name, address in targets.items():
            healthy, detail = snmp_probe(address, args.community, args.snmp_timeout)
            failures[name] = 0 if healthy else failures[name] + 1
            print(
                f"CHECK {name} address={address} healthy={healthy} "
                f"failures={failures[name]}",
                flush=True,
            )

            status: str | None = None
            if failures[name] >= args.failure_threshold and not firing[name]:
                status = "firing"
            elif healthy and firing[name]:
                status = "resolved"

            if status:
                try:
                    send_alert(
                        args.backend_url,
                        alert_payload(name, address, status, detail),
                    )
                    firing[name] = status == "firing"
                    print(f"ALERT {status}: {name}", flush=True)
                except (OSError, urllib.error.URLError, RuntimeError) as exc:
                    print(f"ALERT DELIVERY FAILED: {name}: {exc}", flush=True)

        if args.once:
            return
        time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--community", default="NOC-RO")
    parser.add_argument("--targets", default=DEFAULT_TARGETS)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--snmp-timeout", type=int, default=2)
    parser.add_argument("--once", action="store_true")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
