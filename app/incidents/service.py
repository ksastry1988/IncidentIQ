from datetime import timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.incidents.models import Incident, IncidentCreate
from app.incidents.repository import IncidentRepository


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused for different incident data."""


class IncidentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = IncidentRepository(session)

    def create(self, incident: IncidentCreate) -> Incident:
        existing = self._repository.get_by_idempotency_key(incident.idempotency_key)
        if existing is not None:
            return self._return_existing(existing, incident)

        try:
            return self._repository.create(incident)
        except IntegrityError:
            self._session.rollback()
            existing = self._repository.get_by_idempotency_key(
                incident.idempotency_key
            )
            if existing is None:
                raise
            return self._return_existing(existing, incident)

    @staticmethod
    def _return_existing(existing: Incident, requested: IncidentCreate) -> Incident:
        if not _same_request(existing, requested):
            raise IdempotencyConflictError
        return existing


def _same_request(existing: Incident, requested: IncidentCreate) -> bool:
    existing_detected_at = existing.detected_at
    requested_detected_at = requested.detected_at
    if existing_detected_at.tzinfo is None:
        existing_detected_at = existing_detected_at.replace(tzinfo=timezone.utc)
    if requested_detected_at.tzinfo is None:
        requested_detected_at = requested_detected_at.replace(tzinfo=timezone.utc)

    return (
        existing.service == requested.service
        and existing.title == requested.title
        and existing.description == requested.description
        and existing.severity == requested.severity
        and existing.environment == requested.environment
        and existing_detected_at == requested_detected_at
        and existing.initial_symptoms == requested.initial_symptoms
    )
