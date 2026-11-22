import pytest

from app.api.simulated_deployments import get_deployment_source
from app.simulated_deployments.source import (
    DeploymentQuery,
    SimulatedDeploymentSource,
    SimulatedDeploymentSourceError,
)

URL = "/api/v1/simulated/deployments"
PARAMS = {"service": "payments", "as_of": "2026-11-17T12:00:00Z"}


def query(client, **params):
    return client.get(URL, params={**PARAMS, **params})


def test_returns_required_fields_for_regression_near_incident(client):
    response = query(client, lookback_minutes=60)
    assert response.status_code == 200
    assert response.json() == {
        "service": "payments",
        "start": "2026-11-17T11:00:00Z",
        "end": "2026-11-17T12:00:00Z",
        "deployment_count": 1,
        "deployments": [
            {
                "deployment_id": "dep-1002",
                "service": "payments",
                "version": "v2.14.0",
                "timestamp": "2026-11-17T11:55:00Z",
                "status": "succeeded",
                "change_summary": "Reduce connection pool size and add synchronous fraud-check call",
            }
        ],
    }


def test_lookback_and_service_filtering(client):
    wide = query(client, as_of="2026-11-17T13:00:00Z", lookback_minutes=2880).json()
    assert [d["deployment_id"] for d in wide["deployments"]] == [
        "dep-1001",
        "dep-1002",
        "dep-1003",
    ]
    narrow = query(client, as_of="2026-11-17T13:00:00Z", lookback_minutes=60).json()
    assert [d["deployment_id"] for d in narrow["deployments"]] == ["dep-1003"]
    checkout = query(client, service="checkout", lookback_minutes=180).json()
    assert {d["service"] for d in checkout["deployments"]} == {"checkout"}


def test_fixtures_include_unsuccessful_deployments_and_are_stable(client):
    params = {"service": "checkout", "lookback_minutes": 300}
    first = query(client, **params)
    assert first.json() == query(client, **params).json()
    statuses = {d["status"] for d in first.json()["deployments"]}
    assert statuses == {"succeeded", "failed"}
    rolled_back = query(client, as_of="2026-11-17T13:00:00Z", lookback_minutes=60)
    assert rolled_back.json()["deployments"][0]["status"] == "rolled_back"


def test_no_matching_deployments_is_explicit_empty_result(client):
    for params in ({"service": "unknown"}, {"lookback_minutes": 1, "as_of": "2026-11-17T20:00:00Z"}):
        response = query(client, **params)
        assert response.status_code == 200
        assert response.json()["deployment_count"] == 0
        assert response.json()["deployments"] == []


def test_invalid_queries_are_rejected(client):
    assert query(client, as_of="2026-11-17T12:00:00").status_code == 422
    assert query(client, lookback_minutes=0).status_code == 422
    assert query(client, lookback_minutes=10081).status_code == 422
    assert client.get(URL).status_code == 422


def test_source_failure_is_an_error_not_an_empty_success(client):
    with pytest.raises(SimulatedDeploymentSourceError):
        SimulatedDeploymentSource(unavailable=True).query(DeploymentQuery(**PARAMS))

    client.app.dependency_overrides[get_deployment_source] = lambda: SimulatedDeploymentSource(
        unavailable=True
    )
    try:
        response = query(client)
    finally:
        del client.app.dependency_overrides[get_deployment_source]
    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "simulated_deployment_source_unavailable",
            "message": "The simulated deployment source is unavailable.",
        }
    }
