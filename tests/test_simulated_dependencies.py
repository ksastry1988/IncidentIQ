import pytest

from app.api.simulated_dependencies import get_dependency_source
from app.simulated_dependencies.source import (
    DependencyQuery,
    SimulatedDependencySource,
    SimulatedDependencySourceError,
)

URL = "/api/v1/simulated/dependencies"


def relationships(client, service):
    response = client.get(URL, params={"service": service})
    assert response.status_code == 200
    return response.json()


def test_downstream_degradation_path_with_direction(client):
    body = relationships(client, "checkout")
    assert body["relationship_count"] == len(body["relationships"]) == 4
    assert [
        (r["service"], r["direction"], r["depth"], r["path"])
        for r in body["relationships"]
        if r["service"] in {"inventory", "inventory-db"}
    ] == [
        ("inventory", "depends_on", 1, ["checkout", "inventory"]),
        ("inventory-db", "depends_on", 2, ["checkout", "inventory", "inventory-db"]),
    ]


def test_upstream_callers_are_reported_with_reverse_direction(client):
    body = relationships(client, "inventory-db")
    assert [(r["service"], r["direction"], r["path"]) for r in body["relationships"]] == [
        ("inventory", "depended_on_by", ["inventory", "inventory-db"]),
        ("checkout", "depended_on_by", ["checkout", "inventory", "inventory-db"]),
    ]


def test_results_are_scoped_to_requested_service_and_stable(client):
    first = relationships(client, "search")
    assert [r["service"] for r in first["relationships"]] == ["search-index"]
    assert first == relationships(client, "search")
    related = {r["service"] for r in relationships(client, "checkout")["relationships"]}
    assert "search" not in related and "search-index" not in related


def test_service_without_dependencies_returns_empty_result(client):
    assert relationships(client, "unknown") == {
        "service": "unknown",
        "relationship_count": 0,
        "relationships": [],
    }


def test_service_is_required(client):
    assert client.get(URL).status_code == 422


def test_source_failure_is_an_error_not_an_empty_success(client):
    with pytest.raises(SimulatedDependencySourceError):
        SimulatedDependencySource(unavailable=True).query(
            DependencyQuery(service="checkout")
        )

    client.app.dependency_overrides[get_dependency_source] = lambda: SimulatedDependencySource(
        unavailable=True
    )
    try:
        response = client.get(URL, params={"service": "checkout"})
    finally:
        del client.app.dependency_overrides[get_dependency_source]
    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "simulated_dependency_source_unavailable",
            "message": "The simulated dependency source is unavailable.",
        }
    }
