from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class IncidentCreate:
    idempotency_key: str
    service: str
    title: str
    description: str
    severity: str
    environment: str
    detected_at: datetime
    initial_symptoms: list[str]


@dataclass(frozen=True)
class Incident:
    id: UUID
    idempotency_key: str
    service: str
    title: str
    description: str
    severity: str
    environment: str
    detected_at: datetime
    initial_symptoms: list[str]
    status: str
    created_at: datetime
