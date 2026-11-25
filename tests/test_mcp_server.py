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
    result = await call(name, EMPTY[name])
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
