from datetime import datetime
from uuid import UUID, uuid4

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
        "severity": "severity 1",
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
    "severity", ["severity 1", "severity 2", "severity 3", "severity 4", "severity 5"]
)
def test_supported_severities_are_accepted(api_client, incident_payload, severity):
    client, _ = api_client

    response = client.post(
        "/api/v1/incidents",
        json={**incident_payload, "severity": severity},
        headers={"Idempotency-Key": severity},
    )

    assert response.status_code == 201
    assert response.json()["severity"] == severity


@pytest.mark.parametrize(
    "changes",
    [
        {"title": ""},
        {"service": "  "},
        {"severity": "critical"},
        {"severity": "severity 0"},
        {"severity": "severity 6"},
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


def test_idempotent_replay_normalizes_non_utc_detected_at(
    api_client, incident_payload
):
    client, session_factory = api_client
    headers = {"Idempotency-Key": "offset-alert"}
    offset_payload = {
        **incident_payload,
        "detected_at": "2026-11-17T14:00:00+02:00",
    }

    first = client.post("/api/v1/incidents", json=offset_payload, headers=headers)
    replay = client.post("/api/v1/incidents", json=offset_payload, headers=headers)

    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()
    with session_factory() as session:
        assert session.query(IncidentRecord).count() == 1
        incident = session.query(IncidentRecord).one()
        assert incident.detected_at == datetime(2026, 11, 17, 12, 0)


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


def test_get_incident_reads_persisted_fields_and_current_status(
    api_client, incident_payload
):
    client, session_factory = api_client
    created = client.post(
        "/api/v1/incidents",
        json=incident_payload,
        headers={"Idempotency-Key": "retrieve-alert"},
    )
    assert created.status_code == 201
    incident_id = created.json()["incident_id"]

    with session_factory() as session:
        record = session.get(IncidentRecord, UUID(incident_id))
        record.status = "INVESTIGATING"
        session.commit()
        before = record.to_incident()

    response = client.get(f"/api/v1/incidents/{incident_id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "incident_id",
        "service",
        "title",
        "description",
        "severity",
        "environment",
        "detected_at",
        "initial_symptoms",
        "status",
        "created_at",
    }
    assert body["incident_id"] == incident_id
    for field in (
        "service",
        "title",
        "description",
        "severity",
        "environment",
        "initial_symptoms",
    ):
        assert body[field] == incident_payload[field]
    assert datetime.fromisoformat(body["detected_at"].replace("Z", "+00:00")).replace(
        tzinfo=None
    ) == datetime(2026, 11, 17, 12, 0)
    assert body["created_at"] == created.json()["created_at"]
    assert body["status"] == "INVESTIGATING"
    with session_factory() as session:
        assert session.query(IncidentRecord).count() == 1
        assert session.get(IncidentRecord, UUID(incident_id)).to_incident() == before


def test_get_unknown_incident_returns_404_without_creating_record(api_client):
    client, session_factory = api_client

    response = client.get(f"/api/v1/incidents/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "incident_not_found", "message": "Incident not found."}
    }
    with session_factory() as session:
        assert session.query(IncidentRecord).count() == 0


def test_get_malformed_incident_id_returns_422_without_creating_record(api_client):
    client, session_factory = api_client

    response = client.get("/api/v1/incidents/not-a-uuid")

    assert response.status_code == 422
    with session_factory() as session:
        assert session.query(IncidentRecord).count() == 0


def test_get_database_failure_returns_safe_error(api_client, monkeypatch):
    client, _ = api_client

    def fail_lookup(self, incident_id):
        raise OperationalError(
            "private query", {}, RuntimeError("private database detail")
        )

    monkeypatch.setattr(IncidentRepository, "get", fail_lookup)
    response = client.get(f"/api/v1/incidents/{uuid4()}")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "incident_persistence_unavailable",
            "message": "The incident could not be retrieved.",
        }
    }
