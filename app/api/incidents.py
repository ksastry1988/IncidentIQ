import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.simulated_dependencies import get_dependency_source
from app.dependencies import DbSessionDep
from app.incidents.models import Incident, IncidentCreate
from app.incidents.service import IdempotencyConflictError, IncidentService
from app.simulated_dependencies.source import (
    DependencyQuery,
    ServiceDependencies,
    SimulatedDependencySource,
    SimulatedDependencySourceError,
)

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


class IncidentResponse(BaseModel):
    incident_id: UUID
    service: str
    title: str
    description: str
    severity: str
    environment: str
    detected_at: datetime
    initial_symptoms: list[str]
    status: str
    created_at: datetime

    @classmethod
    def from_incident(cls, incident: Incident) -> "IncidentResponse":
        return cls(
            incident_id=incident.id,
            service=incident.service,
            title=incident.title,
            description=incident.description,
            severity=incident.severity,
            environment=incident.environment,
            detected_at=incident.detected_at,
            initial_symptoms=incident.initial_symptoms,
            status=incident.status,
            created_at=incident.created_at,
        )


def get_incident_or_raise(session: Session, incident_id: UUID) -> Incident:
    try:
        incident = IncidentService(session).get(incident_id)
    except SQLAlchemyError:
        logger.exception("Incident retrieval failed due to a database error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "incident_persistence_unavailable",
                "message": "The incident could not be retrieved.",
            },
        ) from None
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "incident_not_found", "message": "Incident not found."},
        )
    return incident


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    responses={
        404: {"description": "Incident not found"},
        503: {"description": "Incident storage unavailable"},
    },
)
def get_incident(incident_id: UUID, session: DbSessionDep) -> IncidentResponse:
    return IncidentResponse.from_incident(get_incident_or_raise(session, incident_id))


class IncidentDependenciesResponse(ServiceDependencies):
    incident_id: UUID


@router.get(
    "/{incident_id}/dependencies",
    response_model=IncidentDependenciesResponse,
    responses={
        404: {"description": "Incident not found"},
        503: {"description": "Incident storage or dependency source unavailable"},
    },
)
def get_incident_dependencies(
    incident_id: UUID,
    session: DbSessionDep,
    source: Annotated[SimulatedDependencySource, Depends(get_dependency_source)],
) -> IncidentDependenciesResponse:
    incident = get_incident_or_raise(session, incident_id)
    try:
        dependencies = source.query(DependencyQuery(service=incident.service))
    except SimulatedDependencySourceError:
        logger.exception("Incident dependency lookup failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "simulated_dependency_source_unavailable",
                "message": "The simulated dependency source is unavailable.",
            },
        ) from None
    return IncidentDependenciesResponse(
        incident_id=incident.id, **dependencies.model_dump()
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
