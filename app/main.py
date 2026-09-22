import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Incident, IncidentEvent, IncidentStatus, Severity
from app.schemas import AlertPayload, AnalysisRead, IncidentCreate, IncidentEventCreate, IncidentRead, StatusUpdate
from app.services.analysis import analyze_incident

REQUESTS = Counter("autonomous_noc_http_requests_total", "HTTP requests", ["method", "path", "status"])
DURATION = Histogram("autonomous_noc_http_request_duration_seconds", "HTTP request duration", ["path"])
INCIDENTS = Counter("autonomous_noc_incidents_created_total", "Created incidents", ["severity"])
AI_ANALYSES = Counter(
    "autonomous_noc_ai_analyses_total",
    "AI incident analyses",
    ["provider", "risk", "recommended_action"],
)
LAST_AI_ANALYSIS = Gauge(
    "autonomous_noc_last_ai_analysis",
    "Latest AI analysis metadata by affected service",
    ["affected_service", "provider", "risk", "recommended_action"],
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Autonomous NOC", version="0.1.0", lifespan=lifespan)
NMS_AGENT_PATH = Path("/app/agents/nms-snmp-agent.py")
NMS_SYSLOG_AGENT_PATH = Path("/app/agents/nms-syslog-agent.py")


def add_event(
    db: Session,
    incident_id: str,
    event_type: str,
    source: str,
    message: str,
    details: dict | None = None,
):
    db.add(IncidentEvent(
        incident_id=incident_id,
        event_type=event_type,
        source=source,
        message=message,
        details_json=json.dumps(details or {}, ensure_ascii=False),
    ))


def event_to_dict(event: IncidentEvent) -> dict:
    return {
        "id": event.id,
        "incident_id": event.incident_id,
        "event_type": event.event_type,
        "source": event.source,
        "message": event.message,
        "details": json.loads(event.details_json or "{}"),
        "created_at": event.created_at,
    }


@app.middleware("http")
async def observe(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    REQUESTS.labels(request.method, request.url.path, response.status_code).inc()
    DURATION.labels(request.url.path).observe(time.perf_counter() - started)
    return response


@app.get("/")
def root():
    return {"name": "Autonomous NOC", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/agents/nms-snmp-agent.py", include_in_schema=False)
def download_nms_snmp_agent():
    if not NMS_AGENT_PATH.is_file():
        raise HTTPException(404, "NMS agent is not included in this build")
    return FileResponse(
        NMS_AGENT_PATH,
        media_type="text/x-python; charset=utf-8",
        filename="nms-snmp-agent.py",
    )


@app.get("/agents/nms-syslog-agent.py", include_in_schema=False)
def download_nms_syslog_agent():
    if not NMS_SYSLOG_AGENT_PATH.is_file():
        raise HTTPException(404, "NMS syslog agent is not included in this build")
    return FileResponse(
        NMS_SYSLOG_AGENT_PATH,
        media_type="text/x-python; charset=utf-8",
        filename="nms-syslog-agent.py",
    )


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/incidents", response_model=IncidentRead, status_code=201)
def create_incident(payload: IncidentCreate, db: Session = Depends(get_db)):
    item = Incident(**payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "fingerprint already exists")
    db.refresh(item)
    add_event(db, item.id, "INCIDENT_CREATED", payload.source, "Incident oluşturuldu", {
        "status": item.status.value, "severity": item.severity.value
    })
    db.commit()
    INCIDENTS.labels(item.severity.value).inc()
    return item


@app.get("/incidents", response_model=list[IncidentRead])
def list_incidents(db: Session = Depends(get_db)):
    return db.scalars(select(Incident).order_by(Incident.created_at.desc())).all()


def get_incident_or_404(incident_id: str, db: Session) -> Incident:
    item = db.get(Incident, incident_id)
    if not item:
        raise HTTPException(404, "incident not found")
    return item


@app.get("/incidents/{incident_id}", response_model=IncidentRead)
def get_incident(incident_id: str, db: Session = Depends(get_db)):
    return get_incident_or_404(incident_id, db)


@app.patch("/incidents/{incident_id}/status", response_model=IncidentRead)
def update_status(incident_id: str, payload: StatusUpdate, db: Session = Depends(get_db)):
    item = get_incident_or_404(incident_id, db)
    allowed = {IncidentStatus.open: {IncidentStatus.investigating}, IncidentStatus.investigating: {IncidentStatus.resolved},
               IncidentStatus.resolved: {IncidentStatus.closed, IncidentStatus.investigating}, IncidentStatus.closed: set()}
    if payload.status != item.status and payload.status not in allowed[item.status]:
        raise HTTPException(409, f"invalid transition: {item.status.value} -> {payload.status.value}")
    previous = item.status
    item.status = payload.status
    if previous != payload.status:
        add_event(db, item.id, "STATUS_CHANGED", "api", "Incident durumu değiştirildi", {
            "from": previous.value, "to": payload.status.value
        })
    db.commit(); db.refresh(item)
    return item


@app.get("/incidents/{incident_id}/ai-analysis", response_model=AnalysisRead)
def ai_analysis(incident_id: str, db: Session = Depends(get_db)):
    item = get_incident_or_404(incident_id, db)
    result = analyze_incident(item)
    item.root_cause = result["root_cause"]
    item.confidence_score = result["confidence_score"]
    add_event(db, item.id, "AI_ANALYSIS", result.get("provider", "unknown"), "Yapay zekâ analizi tamamlandı", {
        "root_cause": result["root_cause"],
        "confidence_score": result["confidence_score"],
        "recommended_action": result.get("recommended_action"),
        "risk": result.get("risk"),
    })
    db.commit()
    provider = result.get("provider", "unknown")
    risk = result.get("risk", "UNKNOWN")
    action = result.get("recommended_action", "unknown")
    AI_ANALYSES.labels(provider, risk, action).inc()
    LAST_AI_ANALYSIS.labels(item.affected_service, provider, risk, action).set(1)
    return {"incident_id": item.id, **result}


@app.post("/alerts/prometheus")
def prometheus_webhook(payload: AlertPayload, db: Session = Depends(get_db)):
    changed = []
    for alert in payload.alerts:
        fingerprint = alert.fingerprint or "|".join(f"{k}={v}" for k, v in sorted(alert.labels.items()))
        existing = db.scalar(select(Incident).where(Incident.fingerprint == fingerprint))
        if alert.status == "resolved" and existing:
            # Monitoring recovery is not an operator-approved resolution.
            # Keep the incident pending review until a human resolves it.
            if existing.status == IncidentStatus.open:
                existing.status = IncidentStatus.investigating
                add_event(db, existing.id, "TECHNICAL_RECOVERY", alert.labels.get("source", "prometheus"),
                          "Alarm teknik olarak düzeldi; operatör incelemesi bekleniyor", {
                              "alert_status": "resolved", "new_status": "investigating"
                          })
                changed.append(existing.id)
        elif alert.status == "firing":
            if existing and existing.status in {
                IncidentStatus.investigating,
                IncidentStatus.resolved,
                IncidentStatus.closed,
            }:
                existing.status = IncidentStatus.open
                existing.description = alert.annotations.get("description", existing.description)
                add_event(db, existing.id, "ALERT_REFIRING", alert.labels.get("source", "prometheus"),
                          "Alarm yeniden aktifleşti", {"alert_status": "firing"})
                changed.append(existing.id)
            elif not existing:
                severity = alert.labels.get("severity", "high").lower()
                if severity not in {x.value for x in Severity}: severity = "high"
                item = Incident(title=alert.annotations.get("summary", alert.labels.get("alertname", "Prometheus alarm")),
                                description=alert.annotations.get("description", ""), severity=Severity(severity),
                                source=alert.labels.get("source", "prometheus"),
                                affected_service=alert.labels.get("service", alert.labels.get("instance", "unknown")),
                                fingerprint=fingerprint)
                db.add(item); db.flush(); changed.append(item.id); INCIDENTS.labels(severity).inc()
                add_event(db, item.id, "ALERT_FIRING", alert.labels.get("source", "prometheus"),
                          "Yeni alarm alındı", {
                              "alertname": alert.labels.get("alertname"),
                              "fingerprint": fingerprint,
                          })
    db.commit()
    return {"processed": len(payload.alerts), "changed_incidents": changed}


@app.get("/incidents/{incident_id}/events")
def incident_events(incident_id: str, db: Session = Depends(get_db)):
    get_incident_or_404(incident_id, db)
    events = db.scalars(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at.asc())
    ).all()
    return [event_to_dict(event) for event in events]


@app.post("/incidents/{incident_id}/events", status_code=201)
def create_incident_event(
    incident_id: str,
    payload: IncidentEventCreate,
    db: Session = Depends(get_db),
):
    get_incident_or_404(incident_id, db)
    add_event(db, incident_id, payload.event_type, payload.source, payload.message, payload.details)
    db.commit()
    event = db.scalar(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at.desc())
    )
    return event_to_dict(event)
