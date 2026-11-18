from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.base import Base
from app.db.models import IncidentRecord
from app.dependencies import get_db_session
from app.incidents.repository import IncidentRepository
from app.main import create_app


@pytest.fixture
def api_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(Settings(database_url="sqlite:///:memory:", environment="test"))

    def override_db_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    with TestClient(app) as client:
        yield client, session_factory
    engine.dispose()


@pytest.fixture
def incident_payload():
    return {
        "service": "payments",
        "title": "Elevated error rate",
        "description": "Payment requests are failing.",
        "severity": "critical",
        "environment": "production",
        "detected_at": "2026-11-17T12:00:00Z",
        "initial_symptoms": ["HTTP 500 responses", "Elevated latency"],
    }


def test_create_incident_returns_hld_response(api_client, incident_payload):
    client, _ = api_client

    response = client.post(
        "/api/v1/incidents",
        json=incident_payload,
        headers={"Idempotency-Key": "alert-001"},
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "incident_id",
        "title",
        "description",
        "severity",
        "affected_services",
        "created_at",
        "status",
    }
    assert UUID(body["incident_id"])
    assert body["title"] == incident_payload["title"]
    assert body["affected_services"] == ["payments"]
    assert body["status"] == "RECEIVED"
    assert datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))


@pytest.mark.parametrize(
    "changes",
    [
        {"title": ""},
        {"service": "  "},
        {"detected_at": "not-a-timestamp"},
        {"detected_at": "2026-11-17T12:00:00"},
        {"initial_symptoms": [""]},
    ],
)
def test_invalid_incident_does_not_create_record(
    api_client, incident_payload, changes
):
    client, session_factory = api_client

    response = client.post(
        "/api/v1/incidents",
        json={**incident_payload, **changes},
        headers={"Idempotency-Key": "invalid-alert"},
    )

    assert response.status_code == 422
    with session_factory() as session:
        assert session.query(IncidentRecord).count() == 0


@pytest.mark.parametrize(
    ("payload", "headers"),
    [
        ({"service": "payments"}, {"Idempotency-Key": "missing-fields"}),
        (None, {}),
    ],
)
def test_missing_request_data_does_not_create_record(
    api_client, incident_payload, payload, headers
):
    client, session_factory = api_client

    response = client.post(
        "/api/v1/incidents",
        json=payload if payload is not None else incident_payload,
        headers=headers,
    )

    assert response.status_code == 422
    with session_factory() as session:
        assert session.query(IncidentRecord).count() == 0


def test_idempotent_replay_returns_same_incident_without_duplicate(
    api_client, incident_payload
):
    client, session_factory = api_client
    headers = {"Idempotency-Key": "alert-001"}

    first = client.post("/api/v1/incidents", json=incident_payload, headers=headers)
    replay = client.post("/api/v1/incidents", json=incident_payload, headers=headers)

    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()
    with session_factory() as session:
        assert session.query(IncidentRecord).count() == 1


def test_idempotency_key_conflict_returns_409(api_client, incident_payload):
    client, session_factory = api_client
    headers = {"Idempotency-Key": "alert-001"}
    client.post("/api/v1/incidents", json=incident_payload, headers=headers)

    response = client.post(
        "/api/v1/incidents",
        json={**incident_payload, "title": "Different incident"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_key_conflict"
    with session_factory() as session:
        assert session.query(IncidentRecord).count() == 1


def test_database_failure_returns_explicit_error(
    api_client, incident_payload, monkeypatch
):
    client, _ = api_client

    def fail_lookup(self, idempotency_key):
        raise OperationalError("select", {}, RuntimeError("database unavailable"))

    monkeypatch.setattr(IncidentRepository, "get_by_idempotency_key", fail_lookup)
    response = client.post(
        "/api/v1/incidents",
        json=incident_payload,
        headers={"Idempotency-Key": "alert-001"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "incident_persistence_unavailable",
            "message": "The incident could not be persisted.",
        }
    }
