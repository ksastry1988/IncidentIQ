from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.incidents.models import IncidentCreate
from app.incidents.repository import IncidentRepository


@pytest.fixture
def session_factory(tmp_path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'incidents.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def new_incident() -> IncidentCreate:
    return IncidentCreate(
        idempotency_key="alert-001",
        service="payments",
        title="Elevated error rate",
        description="Payment requests are failing.",
        severity="critical",
        environment="production",
        detected_at=datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc),
        initial_symptoms=["HTTP 500 responses", "Elevated latency"],
    )


def test_create_and_lookup_round_trip_in_a_new_session(session_factory, new_incident):
    with session_factory() as session:
        created = IncidentRepository(session).create(new_incident)

    with session_factory() as session:
        repository = IncidentRepository(session)
        loaded = repository.get(created.id)
        loaded_by_key = repository.get_by_idempotency_key("alert-001")

    assert loaded == created
    assert loaded_by_key == created
    assert isinstance(created.id, UUID)
    assert created.status == "RECEIVED"
    assert created.initial_symptoms == ["HTTP 500 responses", "Elevated latency"]


def test_duplicate_idempotency_key_surfaces_database_error(
    session_factory, new_incident
):
    with session_factory() as session:
        repository = IncidentRepository(session)
        repository.create(new_incident)
        with pytest.raises(IntegrityError):
            repository.create(new_incident)
        session.rollback()

    with session_factory() as session:
        assert session.query(Base.metadata.tables["incidents"]).count() == 1


def test_missing_incident_returns_none(session_factory):
    with session_factory() as session:
        assert IncidentRepository(session).get(UUID(int=1)) is None


def test_migration_applies_and_rolls_back(tmp_path):
    from alembic import command
    from alembic.config import Config

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    config = Config("alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        inspector = inspect(connection)
        assert "incidents" in inspector.get_table_names()
        assert any(
            constraint["name"] == "uq_incidents_idempotency_key"
            for constraint in inspector.get_unique_constraints("incidents")
        )

        command.downgrade(config, "base")
        assert "incidents" not in inspect(connection).get_table_names()
    engine.dispose()
