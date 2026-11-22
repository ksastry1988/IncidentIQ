import pytest

from app.api.simulated_metrics import get_metrics_source
from app.simulated_metrics.source import (
    MetricsQuery,
    SimulatedMetricsSource,
    SimulatedMetricsSourceError,
)


URL = "/api/v1/simulated/metrics"
BASE_QUERY = {
    "service": "payments",
    "incident_start": "2026-11-17T12:00:00Z",
    "incident_end": "2026-11-17T12:05:00Z",
    "baseline_start": "2026-11-17T11:45:00Z",
    "baseline_end": "2026-11-17T11:50:00Z",
}


def query(client, **params):
    return client.get(URL, params={**BASE_QUERY, **params})


def test_query_returns_all_metrics_and_incident_baseline_comparison(client):
    response = query(client)
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "service": "payments",
        "incident": {
            "start": "2026-11-17T12:00:00Z",
            "end": "2026-11-17T12:05:00Z",
            "sample_count": 2,
            "data_available": True,
            "request_volume": 245,
            "p50_latency_ms": 310.0,
            "p95_latency_ms": 1250.0,
            "p99_latency_ms": 2650.0,
            "error_rate": 8.5,
            "cpu_percent": 53.0,
            "memory_percent": 65.5,
        },
        "baseline": {
            "start": "2026-11-17T11:45:00Z",
            "end": "2026-11-17T11:50:00Z",
            "sample_count": 2,
            "data_available": True,
            "request_volume": 205,
            "p50_latency_ms": 81.0,
            "p95_latency_ms": 152.5,
            "p99_latency_ms": 255.0,
            "error_rate": 0.45,
            "cpu_percent": 45.5,
            "memory_percent": 60.5,
        },
    }


def test_scenario_fixtures_are_stable_and_observable(client):
    scenarios = [
        ("payments", "12:00", "12:05", "11:45", "11:50", "error_rate"),
        ("checkout", "13:00", "13:05", "12:50", "12:55", "p95_latency_ms"),
        ("search", "14:00", "14:05", "13:50", "13:55", "cpu_percent"),
    ]
    for service, incident_start, incident_end, baseline_start, baseline_end, field in scenarios:
        params = {
            "service": service,
            "incident_start": f"2026-11-17T{incident_start}:00Z",
            "incident_end": f"2026-11-17T{incident_end}:00Z",
            "baseline_start": f"2026-11-17T{baseline_start}:00Z",
            "baseline_end": f"2026-11-17T{baseline_end}:00Z",
        }
        first = query(client, **params)
        assert first.status_code == 200
        assert first.json() == query(client, **params).json()
        assert first.json()["incident"][field] > first.json()["baseline"][field]


def test_time_windows_are_inclusive_and_select_only_matching_samples(client):
    response = query(
        client,
        incident_start="2026-11-17T12:05:00Z",
        incident_end="2026-11-17T12:05:00Z",
    )
    assert response.status_code == 200
    incident = response.json()["incident"]
    assert incident["sample_count"] == 1
    assert incident["request_volume"] == 125


def test_source_can_be_queried_directly_and_propagates_failures():
    source_query = MetricsQuery(**BASE_QUERY)
    result = SimulatedMetricsSource().query(source_query)
    assert result.incident.request_volume == 245
    assert result.baseline.request_volume == 205
    with pytest.raises(SimulatedMetricsSourceError):
        SimulatedMetricsSource(unavailable=True).query(source_query)


def test_missing_metric_data_is_explicit(client):
    response = query(
        client,
        service="unknown",
        incident_start="2026-11-17T12:00:00Z",
        incident_end="2026-11-17T12:05:00Z",
    )
    assert response.status_code == 200
    incident = response.json()["incident"]
    assert incident == {
        "start": "2026-11-17T12:00:00Z",
        "end": "2026-11-17T12:05:00Z",
        "sample_count": 0,
        "data_available": False,
        "request_volume": None,
        "p50_latency_ms": None,
        "p95_latency_ms": None,
        "p99_latency_ms": None,
        "error_rate": None,
        "cpu_percent": None,
        "memory_percent": None,
    }


def test_missing_one_window_does_not_hide_the_other(client):
    response = query(
        client,
        incident_start="2026-11-17T15:00:00Z",
        incident_end="2026-11-17T15:05:00Z",
    )
    assert response.status_code == 200
    assert response.json()["incident"]["data_available"] is False
    assert response.json()["incident"]["request_volume"] is None
    assert response.json()["baseline"]["data_available"] is True
    assert response.json()["baseline"]["request_volume"] == 205


def test_invalid_or_missing_windows_are_rejected(client):
    assert query(client, incident_start="2026-11-17T12:00:00").status_code == 422
    assert query(client, incident_start="2026-11-17T12:06:00Z").status_code == 422
    assert query(client, baseline_start="2026-11-17T11:51:00Z").status_code == 422
    assert client.get(URL).status_code == 422


def test_simulated_source_failure_is_not_an_empty_success(client):
    client.app.dependency_overrides[get_metrics_source] = lambda: SimulatedMetricsSource(
        unavailable=True
    )
    try:
        response = query(client)
    finally:
        del client.app.dependency_overrides[get_metrics_source]
    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "simulated_metrics_source_unavailable",
            "message": "The simulated metrics source is unavailable.",
        }
    }
