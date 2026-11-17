from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.incidents.models import Incident


class IncidentRecord(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_incidents_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    service: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    environment: Mapped[str] = mapped_column(String(100), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_symptoms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="RECEIVED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def to_incident(self) -> Incident:
        return Incident(
            id=self.id,
            idempotency_key=self.idempotency_key,
            service=self.service,
            title=self.title,
            description=self.description,
            severity=self.severity,
            environment=self.environment,
            detected_at=self.detected_at,
            initial_symptoms=self.initial_symptoms,
            status=self.status,
            created_at=self.created_at,
        )
