from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IncidentRecord
from app.incidents.models import Incident, IncidentCreate


class IncidentRepository:
    """Persistence operations for incidents; database errors are propagated."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, incident: IncidentCreate) -> Incident:
        record = IncidentRecord(
            idempotency_key=incident.idempotency_key,
            service=incident.service,
            title=incident.title,
            description=incident.description,
            severity=incident.severity,
            environment=incident.environment,
            detected_at=incident.detected_at,
            initial_symptoms=incident.initial_symptoms,
        )
        self._session.add(record)
        self._session.commit()
        self._session.refresh(record)
        return record.to_incident()

    def get(self, incident_id: UUID) -> Incident | None:
        record = self._session.get(IncidentRecord, incident_id)
        return record.to_incident() if record is not None else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Incident | None:
        record = self._session.scalar(
            select(IncidentRecord).where(
                IncidentRecord.idempotency_key == idempotency_key
            )
        )
        return record.to_incident() if record is not None else None
