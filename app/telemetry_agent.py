import json
import os
import subprocess
import time
import urllib.request


def parse_targets(raw: str) -> dict[str, str]:
    targets = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        name, address = item.split("=", 1)
        targets[name.strip()] = address.strip()
    return targets


def probe(address: str, timeout: int = 2) -> bool:
    result = subprocess.run(
        ["ping", "-c", "1", "-W", str(timeout), address],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def alert_payload(name: str, address: str, status: str) -> dict:
    return {
        "alerts": [{
            "status": status,
            "labels": {
                "alertname": "NetworkNodeDown",
                "severity": "critical",
                "service": name,
                "instance": address,
            },
            "annotations": {
                "summary": f"{name} network node is unreachable",
                "description": f"Telemetry agent cannot reach {address}.",
            },
            "fingerprint": f"network-node-down:{name}:{address}",
        }]
    }


def send_alert(backend_url: str, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{backend_url.rstrip('/')}/alerts/prometheus",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()


def run() -> None:
    targets = parse_targets(os.getenv(
        "TELEMETRY_TARGETS",
        "r1-core=clab-autonomous-noc-r1-core,r2-edge=clab-autonomous-noc-r2-edge,"
        "r3-bng=clab-autonomous-noc-r3-bng,client-vlan100=clab-autonomous-noc-client-vlan100",
    ))
    backend_url = os.getenv("BACKEND_URL", "http://backend:8000")
    interval = int(os.getenv("TELEMETRY_INTERVAL_SECONDS", "10"))
    failure_threshold = int(os.getenv("TELEMETRY_FAILURE_THRESHOLD", "3"))
    failures = {name: 0 for name in targets}
    firing = {name: False for name in targets}

    while True:
        for name, address in targets.items():
            reachable = probe(address)
            failures[name] = 0 if reachable else failures[name] + 1
            if failures[name] >= failure_threshold and not firing[name]:
                try:
                    send_alert(backend_url, alert_payload(name, address, "firing"))
                    firing[name] = True
                    print(f"ALERT firing: {name} ({address})", flush=True)
                except Exception as exc:
                    print(f"Alert delivery failed: {exc}", flush=True)
            elif reachable and firing[name]:
                try:
                    send_alert(backend_url, alert_payload(name, address, "resolved"))
                    firing[name] = False
                    print(f"ALERT resolved: {name} ({address})", flush=True)
                except Exception as exc:
                    print(f"Resolution delivery failed: {exc}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    run()

