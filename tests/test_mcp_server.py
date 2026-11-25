import pytest
from mcp import Client

from app.investigation_tools import ToolLimits, ToolRegistry
from app.investigation_tools.server import create_server

RANGE = {"start": "2026-11-17T11:00:00Z", "end": "2026-11-17T13:00:00Z"}
BASE = {"service": "payments", "environment": "production"}
PAST = {"start": "2020-01-01T00:00:00Z", "end": "2020-01-01T01:00:00Z"}
TOOLS = {
    "logs": ("simulated-logs", {**BASE, **RANGE}),
    "metrics": ("simulated-metrics", {**BASE, **RANGE}),
    "deployments": ("simulated-deployments", {**BASE, **RANGE}),
    "dependencies": ("simulated-dependencies", BASE),
}
# Valid queries that match nothing (metrics always return both windows).
EMPTY = {
    "logs": {**BASE, **PAST},
    "deployments": {**BASE, **PAST},
    "dependencies": {**BASE, "service": "no-such-service"},
}


async def call(name, args, registry=None):
    async with Client(create_server(registry)) as client:
        return await client.call_tool(name, args)


async def test_lists_only_the_four_read_only_tools():
    async with Client(create_server()) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == set(TOOLS)
    for t in tools:
        assert {"service", "environment"} <= set(t.input_schema["required"])
        assert t.annotations.read_only_hint is True


@pytest.mark.parametrize("name", TOOLS)
async def test_call_returns_envelope_with_source(name):
    source, args = TOOLS[name]
    result = await call(name, args)
    assert not result.is_error
    assert result.structured_content["source"] == source
    assert result.structured_content["tool"] == name
    assert result.structured_content["items"]


@pytest.mark.parametrize("name", EMPTY)
async def test_no_matches_is_successful_empty_result(name):
    registry = ToolRegistry(policy=AccessPolicy(["payments", "no-such-service"], ["production"]))
    result = await call(name, EMPTY[name], registry)
    assert not result.is_error
    assert result.structured_content["items"] == []


async def test_invalid_arguments_and_unknown_tool_are_errors():
    bad = await call("logs", {"service": "payments"})
    assert bad.is_error and bad.structured_content["validation_errors"]
    assert (await call("delete_logs", {})).is_error


async def test_server_uses_supplied_registry():
    registry = ToolRegistry(limits=ToolLimits(default_limit=1, max_limit=1))
    result = await call("logs", {**BASE, **RANGE}, registry)
    assert len(result.structured_content["items"]) == 1


# --- access policy and read-only enforcement ---

import logging  # noqa: E402

from app.config import ToolAccessSettings  # noqa: E402
from app.investigation_tools import (  # noqa: E402
    DependenciesAdapter, DeploymentsAdapter, LogsAdapter, MetricsAdapter, ToolAdapter,
)
from app.investigation_tools.access import AccessPolicy  # noqa: E402


class CountingAdapter(DependenciesAdapter):
    calls = 0

    def fetch(self, params):
        type(self).calls += 1
        return [{"service": params.service, "environment": params.environment}]


def policy_registry():
    CountingAdapter.calls = 0
    return ToolRegistry(
        [CountingAdapter()], policy=AccessPolicy(["payments"], ["production"])
    )


async def test_authorized_call_succeeds():
    result = await call("dependencies", BASE, policy_registry())
    assert not result.is_error and CountingAdapter.calls == 1


@pytest.mark.parametrize(
    "args,field",
    [
        ({"service": "billing", "environment": "production"}, "service"),
        ({"service": "payments", "environment": "staging"}, "environment"),
        ({"service": ["payments"], "environment": "production"}, "service"),
        ({"service": "payments\u200b", "environment": "production"}, "service"),
    ],
)
async def test_unauthorized_call_is_denied_before_source_query(args, field):
    result = await call("dependencies", args, policy_registry())
    assert result.is_error
    assert result.structured_content == {"error": "access_denied", "field": field}
    assert CountingAdapter.calls == 0


@pytest.mark.parametrize("service", ["PAYMENTS", "  payments\t", "Payments\n"])
async def test_casing_and_whitespace_variants_use_canonical_value(service):
    result = await call("dependencies", {**BASE, "service": service}, policy_registry())
    assert not result.is_error
    assert result.structured_content["service"] == "payments"
    assert result.structured_content["items"] == [BASE]


def test_denied_calls_are_logged_without_values(caplog):
    # Alembic's fileConfig in other tests can disable existing loggers.
    logging.getLogger("app.investigation_tools.mcp").disabled = False
    with caplog.at_level(logging.WARNING):
        policy_registry().call_tool("dependencies", {**BASE, "service": "secret-svc"})
    assert "access denied" in caplog.text and "field=service" in caplog.text
    assert "secret-svc" not in caplog.text


def test_policy_loaded_from_settings():
    policy = AccessPolicy.from_settings(
        ToolAccessSettings(_env_file=None, tool_allowed_services=" a , B ", tool_allowed_environments="dev")
    )
    assert policy.authorize({"service": "b", "environment": "DEV"}) == {"service": "B", "environment": "dev"}


def test_adapters_expose_only_read_operations():
    allowed = {"execute", "fetch", "input_schema", "params_model"}
    for cls in (LogsAdapter, MetricsAdapter, DeploymentsAdapter, DependenciesAdapter):
        assert issubclass(cls, ToolAdapter)
        public = {n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n))}
        assert public <= allowed, public - allowed
    names = {t["name"] for t in ToolRegistry().list_tools()}
    assert not any(v in n for n in names for v in ("write", "delete", "update", "create", "restart"))
