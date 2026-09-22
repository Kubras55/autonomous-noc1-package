from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.models import IncidentStatus, Severity


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    severity: Severity
    source: str
    affected_service: str = "unknown"
    fingerprint: str | None = None


class IncidentRead(IncidentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: IncidentStatus
    root_cause: str | None
    confidence_score: float | None
    created_at: datetime
    updated_at: datetime


class StatusUpdate(BaseModel):
    status: IncidentStatus


class IncidentEventCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=80)
    source: str = Field(default="system", max_length=100)
    message: str = ""
    details: dict = {}


class AnalysisRead(BaseModel):
    incident_id: str
    provider: str
    summary: str
    root_cause: str
    confidence_score: float
    recommended_action: str
    risk: str


class PrometheusAlert(BaseModel):
    status: str
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    fingerprint: str | None = None


class AlertPayload(BaseModel):
    alerts: list[PrometheusAlert]
