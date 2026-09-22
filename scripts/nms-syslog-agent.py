"""Follow Cisco syslog output and forward link/OSPF alarms to Autonomous NOC."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request


PREFIX = re.compile(r"(?:\d+:\s+)?(?P<device>[A-Za-z0-9_-]+):\s+.*?(?P<message>%.*)$")
LINK = re.compile(
    r"%(?:LINK|LINEPROTO)-\d+-(?:CHANGED|UPDOWN): Interface (?P<interface>\S+), "
    r"changed state to (?P<state>administratively down|down|up)",
    re.IGNORECASE,
)
OSPF = re.compile(
    r"%OSPF-\d+-ADJCHG: Process (?P<process>\d+), Nbr (?P<neighbor>\S+) on "
    r"(?P<interface>\S+) from (?P<old>\S+) to (?P<new>\S+),?\s*(?P<reason>.*)",
    re.IGNORECASE,
)


def send_alert(backend_url: str, alert: dict, timeout: int = 10) -> None:
    request = urllib.request.Request(
        f"{backend_url.rstrip('/')}/alerts/prometheus",
        data=json.dumps({"alerts": [alert]}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def make_alert(
    *, status: str, alertname: str, severity: str, device: str,
    interface: str, summary: str, description: str, fingerprint: str,
) -> dict:
    return {
        "status": status,
        "labels": {
            "alertname": alertname,
            "severity": severity,
            "service": device,
            "interface": interface,
            "source": "nms-syslog",
        },
        "annotations": {"summary": summary, "description": description},
        "fingerprint": fingerprint,
    }


def parse_line(line: str) -> list[dict]:
    prefix = PREFIX.search(line)
    if not prefix:
        return []
    device = prefix.group("device")
    message = prefix.group("message")

    link = LINK.search(message)
    if link:
        interface = link.group("interface")
        state = link.group("state").lower()
        status = "resolved" if state == "up" else "firing"
        return [make_alert(
            status=status,
            alertname="SyslogInterfaceDown",
            severity="critical",
            device=device,
            interface=interface,
            summary=(
                f"{device} {interface} bağlantısı düzeldi"
                if status == "resolved" else
                f"{device} {interface} bağlantısı kapandı"
            ),
            description=f"Cisco syslog arayüz durumunu '{state}' olarak bildirdi. Ham kayıt: {message}",
            fingerprint=f"nms-syslog-link:{device}:{interface}",
        )]

    ospf = OSPF.search(message)
    if ospf:
        interface = ospf.group("interface")
        neighbor = ospf.group("neighbor")
        new_state = ospf.group("new").upper()
        status = "resolved" if new_state.startswith("FULL") else "firing"
        return [make_alert(
            status=status,
            alertname="SyslogOspfAdjacencyDown",
            severity="high",
            device=device,
            interface=interface,
            summary=(
                f"{device} OSPF komşuluğu yeniden FULL oldu"
                if status == "resolved" else
                f"{device} OSPF komşuluğu düştü"
            ),
            description=(
                f"OSPF process {ospf.group('process')}, komşu {neighbor}, arayüz {interface}, "
                f"yeni durum {new_state}. Neden: {ospf.group('reason') or 'belirtilmedi'}"
            ),
            fingerprint=f"nms-syslog-ospf:{device}:{interface}:{neighbor}",
        )]
    return []


def follow(args: argparse.Namespace) -> None:
    while not os.path.exists(args.log_file):
        print(f"WAIT log_file={args.log_file}", flush=True)
        time.sleep(2)

    with open(args.log_file, "r", encoding="utf-8", errors="replace") as stream:
        if not args.from_start:
            stream.seek(0, os.SEEK_END)
        while True:
            line = stream.readline()
            if not line:
                if args.once:
                    return
                time.sleep(0.5)
                continue
            for alert in parse_line(line):
                try:
                    send_alert(args.backend_url, alert)
                    print(
                        f"ALERT {alert['status']}: {alert['labels']['service']} "
                        f"{alert['labels']['interface']} {alert['labels']['alertname']}",
                        flush=True,
                    )
                except (OSError, urllib.error.URLError, RuntimeError) as exc:
                    print(f"ALERT DELIVERY FAILED: {exc}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--log-file", default="/var/log/network/routers.log")
    parser.add_argument("--from-start", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser


if __name__ == "__main__":
    follow(build_parser().parse_args())
