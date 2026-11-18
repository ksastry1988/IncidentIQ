import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError

from app.dependencies import DbSessionDep
from app.incidents.models import Incident, IncidentCreate
from app.incidents.service import IdempotencyConflictError, IncidentService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    service: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1)
    severity: Literal[
        "severity 1", "severity 2", "severity 3", "severity 4", "severity 5"
    ]
    environment: str = Field(min_length=1, max_length=100)
    detected_at: datetime
    initial_symptoms: list[str] = Field(min_length=1)

    @field_validator("detected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("detected_at must include a timezone")
        return value

    @field_validator("initial_symptoms")
    @classmethod
    def require_nonempty_symptoms(cls, value: list[str]) -> list[str]:
        if any(not symptom.strip() for symptom in value):
            raise ValueError("initial_symptoms entries must not be empty")
        return [symptom.strip() for symptom in value]


class IncidentCreateResponse(BaseModel):
    incident_id: UUID
    title: str
    description: str
    severity: str
    affected_services: list[str]
    created_at: datetime
    status: str

    @classmethod
    def from_incident(cls, incident: Incident) -> "IncidentCreateResponse":
        return cls(
            incident_id=incident.id,
            title=incident.title,
            description=incident.description,
            severity=incident.severity,
            affected_services=[incident.service],
            created_at=incident.created_at,
            status=incident.status,
        )


@router.post(
    "",
    response_model=IncidentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_incident(
    request: IncidentCreateRequest,
    session: DbSessionDep,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ],
) -> IncidentCreateResponse:
    incident = IncidentCreate(
        idempotency_key=idempotency_key,
        service=request.service,
        title=request.title,
        description=request.description,
        severity=request.severity,
        environment=request.environment,
        detected_at=request.detected_at,
        initial_symptoms=request.initial_symptoms,
    )
    try:
        created = IncidentService(session).create(incident)
    except IdempotencyConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "idempotency_key_conflict",
                "message": "The idempotency key was already used for a different request.",
            },
        ) from None
    except SQLAlchemyError:
        logger.exception("Incident creation failed due to a database error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "incident_persistence_unavailable",
                "message": "The incident could not be persisted.",
            },
        ) from None
    return IncidentCreateResponse.from_incident(created)
