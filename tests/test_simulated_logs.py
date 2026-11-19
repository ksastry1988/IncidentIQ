import pytest

from app.api.simulated_logs import get_log_source
from app.simulated_logs.source import MAX_PAGE_SIZE, SimulatedLogSource


URL = "/api/v1/simulated/logs"
BASE_QUERY = {
    "service": "payments",
    "start": "2026-11-17T11:00:00Z",
    "end": "2026-11-17T15:00:00Z",
}


def query(client, **params):
    return client.get(URL, params={**BASE_QUERY, **params})


def ids(response):
    assert response.status_code == 200
    return [event["id"] for event in response.json()["items"]]


def test_filters_are_composable_and_time_range_is_inclusive(client):
    response = query(
        client,
        start="2026-11-17T14:00:00+02:00",
        end="2026-11-17T12:00:00Z",
        severity="ERROR",
        error_pattern="INVALID CONFIGURATION",
        correlation_id="pay-101",
    )
    assert ids(response) == ["deploy-002"]
    assert response.json()["items"][0] == {
        "id": "deploy-002",
        "service": "payments",
        "timestamp": "2026-11-17T12:00:00Z",
        "severity": "ERROR",
        "message": "Payment request failed after deployment: invalid configuration",
        "correlation_id": "pay-101",
    }


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"service": "checkout"}, ["downstream-001", "downstream-003"]),
        ({"start": "2026-11-17T12:01:00Z"}, ["deploy-003"]),
        ({"end": "2026-11-17T11:55:00Z"}, ["deploy-001"]),
        ({"severity": "INFO"}, ["deploy-001"]),
        ({"error_pattern": "INVALID"}, ["deploy-002", "deploy-003"]),
        ({"correlation_id": "pay-102"}, ["deploy-003"]),
    ],
)
def test_individual_filters(client, params, expected):
    assert ids(query(client, **params)) == expected


def test_pagination_is_bounded_and_stable(client):
    first = query(client, page_size=2)
    second = query(client, page=2, page_size=2)
    assert ids(first) == ["deploy-001", "deploy-002"]
    assert first.json()["has_more"] is True
    assert ids(second) == ["deploy-003"]
    assert second.json()["has_more"] is False
    assert first.json() == query(client, page_size=2).json()
    empty_page = query(client, page=3, page_size=2)
    assert ids(empty_page) == []
    assert empty_page.json()["has_more"] is False
    assert query(client, page_size=MAX_PAGE_SIZE).status_code == 200
    assert query(client, page_size=MAX_PAGE_SIZE + 1).status_code == 422


@pytest.mark.parametrize(
    ("service", "expected"),
    [
        ("payments", ["deploy-001", "deploy-002", "deploy-003"]),
        ("checkout", ["downstream-001", "downstream-003"]),
        ("inventory", ["downstream-002"]),
        ("search", ["resource-001", "resource-002"]),
    ],
)
def test_scenario_fixtures_are_deterministic(client, service, expected):
    first = query(client, service=service)
    assert ids(first) == expected
    assert first.json() == query(client, service=service).json()


def test_no_matches_are_explicit_empty_success(client):
    response = query(client, correlation_id="not-found")
    assert response.status_code == 200
    assert response.json() == {
        "items": [], "page": 1, "page_size": 20, "has_more": False
    }


@pytest.mark.parametrize(
    "params",
    [
        {"service": ""},
        {"severity": "critical"},
        {"error_pattern": ""},
        {"correlation_id": ""},
        {"start": "2026-11-17T11:00:00"},
        {"start": "not-a-date"},
        {"start": "2026-11-17T16:00:00Z"},
        {"page": 0},
        {"page_size": 0},
        {"page_size": -1},
    ],
)
def test_invalid_queries_are_rejected(client, params):
    assert query(client, **params).status_code == 422


def test_missing_required_query_parameters_are_rejected(client):
    assert client.get(URL).status_code == 422


def test_simulated_source_failure_is_not_an_empty_success(client):
    client.app.dependency_overrides[get_log_source] = lambda: SimulatedLogSource(
        unavailable=True
    )
    try:
        response = query(client)
    finally:
        del client.app.dependency_overrides[get_log_source]
    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "simulated_log_source_unavailable",
            "message": "The simulated log source is unavailable.",
        }
    }
