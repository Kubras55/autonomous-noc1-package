def sample():
    return {"title": "VLAN 100 erişim hatası", "description": "BNG dot1q mismatch", "severity": "high",
            "source": "lab-r3", "affected_service": "subscriber-vlan-100"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_incident_lifecycle_and_analysis(client):
    created = client.post("/incidents", json=sample())
    assert created.status_code == 201
    incident_id = created.json()["id"]
    assert client.patch(f"/incidents/{incident_id}/status", json={"status": "resolved"}).status_code == 409
    assert client.patch(f"/incidents/{incident_id}/status", json={"status": "investigating"}).status_code == 200
    analysis = client.get(f"/incidents/{incident_id}/ai-analysis")
    assert analysis.status_code == 200
    assert analysis.json()["recommended_action"] == "rollback_vlan_config"


def test_prometheus_deduplication(client):
    payload = {"alerts": [{"status": "firing", "labels": {"alertname": "RouterDown", "severity": "critical"},
                           "annotations": {"summary": "R2 down"}, "fingerprint": "abc"}]}
    assert client.post("/alerts/prometheus", json=payload).json()["changed_incidents"]
    assert client.post("/alerts/prometheus", json=payload).json()["changed_incidents"] == []
    assert len(client.get("/incidents").json()) == 1


def test_telemetry_alert_shape():
    from app.telemetry_agent import alert_payload, parse_targets
    assert parse_targets("core=10.0.0.1, edge=10.0.0.2") == {"core": "10.0.0.1", "edge": "10.0.0.2"}
    alert = alert_payload("r2-edge", "10.0.0.2", "firing")["alerts"][0]
    assert alert["labels"]["alertname"] == "NetworkNodeDown"
    assert alert["fingerprint"] == "network-node-down:r2-edge:10.0.0.2"
