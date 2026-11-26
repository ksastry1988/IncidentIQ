import time

import pytest
from mcp import Client
from pydantic import ValidationError

from app.config import ToolTimeoutSettings
from app.investigation_tools.adapters import DependenciesAdapter, LogsAdapter

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


@pytest.mark.parametrize("name", TOOLS)
async def test_environment_isolation_excludes_production_data_from_staging(name):
    source, args = TOOLS[name]
    registry = ToolRegistry(
        policy=AccessPolicy(["payments"], ["production", "staging"])
    )
    staging_args = {**args, "environment": "staging"}

    production = await call(name, args, registry)
    staging = await call(name, staging_args, registry)

    assert not production.is_error and production.structured_content["items"]
    assert not staging.is_error
    if name == "metrics":
        assert all(not window["data_available"] for window in staging.structured_content["items"])
    else:
        assert staging.structured_content["items"] == []


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


class FakeAdapter(LogsAdapter):
    def __init__(self, behavior):
        super().__init__()
        self.behavior = behavior

    def fetch(self, params):
        return self.behavior()


def _registry(logs_behavior, **kwargs):
    return ToolRegistry(
        adapters=[FakeAdapter(logs_behavior), DependenciesAdapter()], **kwargs
    )


def _slow():
    time.sleep(2)
    return []


def _unavailable():
    raise ConnectionError("db at 10.0.0.5 refused")


async def test_slow_source_returns_timeout_error():
    result = await call("logs", {**BASE, **RANGE}, _registry(_slow, timeout_seconds=0.1))
    assert result.is_error
    assert result.structured_content == {
        "status": "error",
        "error": "timeout",
        "source": "simulated-logs",
    }


async def test_custom_timeout_allows_slower_source():
    def slowish():
        time.sleep(0.2)
        return []

    result = await call("logs", {**BASE, **RANGE}, _registry(slowish, timeout_seconds=2))
    assert not result.is_error
    assert result.structured_content["status"] == "ok"


async def test_source_failure_is_source_error_without_internals():
    result = await call("logs", {**BASE, **RANGE}, _registry(_unavailable))
    assert result.is_error
    assert result.structured_content == {
        "status": "error",
        "error": "source_error",
        "source": "simulated-logs",
    }
    text = result.content[0].text
    assert "Traceback" not in text and "10.0.0.5" not in text


async def test_empty_success_is_distinct_from_errors():
    result = await call("logs", {**BASE, **RANGE}, _registry(lambda: []))
    assert not result.is_error
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["items"] == []
    assert "error" not in result.structured_content


async def test_failing_tool_does_not_block_others():
    registry = _registry(_unavailable)
    assert (await call("logs", {**BASE, **RANGE}, registry)).is_error
    assert not (await call("dependencies", BASE, registry)).is_error


def test_timeout_setting_default_and_validation(monkeypatch):
    monkeypatch.delenv("INCIDENTIQ_TOOL_TIMEOUT_SECONDS", raising=False)
    assert ToolTimeoutSettings(_env_file=None).tool_timeout_seconds == 10
    monkeypatch.setenv("INCIDENTIQ_TOOL_TIMEOUT_SECONDS", "2.5")
    assert ToolRegistry()._timeout == 2.5
    for bad in ("0", "-1"):
        monkeypatch.setenv("INCIDENTIQ_TOOL_TIMEOUT_SECONDS", bad)
        with pytest.raises(ValidationError):
            ToolTimeoutSettings(_env_file=None)
    with pytest.raises(ValueError):
        ToolRegistry(timeout_seconds=0)


# --- Redaction -------------------------------------------------------------
import json  # noqa: E402

from app.investigation_tools.redaction import REDACTED, Redactor  # noqa: E402

SECRET = "s3cr3t-Value-42"


def test_redactor_masks_nested_data_and_field_names():
    data = {
        "password": "hunter2",
        "author": "alice",
        "nested": [{"api_key": "abc123", "ok": 1}, {"deep": {"Authorization": "Bearer abcdefgh12345"}}],
        "token_count": None,
    }
    out, count = Redactor().redact(data)
    assert out["password"] == REDACTED
    assert out["author"] == "alice"
    assert out["nested"][0] == {"api_key": REDACTED, "ok": 1}
    assert out["nested"][1]["deep"]["Authorization"] == REDACTED
    assert out["token_count"] is None
    assert count == 3


@pytest.mark.parametrize(
    "message",
    [
        "login failed password=hunter2 for user",
        'payload {"api_key": "abc123xyz"}',
        "Authorization: Bearer abcdef123456",
        "connect postgresql://app:hunter2@db:5432/x failed",
        "Server=db;User Id=sa;Password=hunter2;Encrypt=true",
        "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc",
    ],
)
def test_redactor_masks_log_messages(message):
    out, count = Redactor().redact(message)
    assert count >= 1
    assert "hunter2" not in out and "abc123" not in out and "eyJ" not in out
    assert REDACTED in out


def test_redactor_masks_configured_secrets_anywhere():
    out, count = Redactor([SECRET]).redact({f"k-{SECRET}": f"x {SECRET} y"})
    assert SECRET not in json.dumps(out) and count == 2


class LeakyLogs(LogsAdapter):
    def fetch(self, params):
        return [
            {"message": f"db password=hunter2 {SECRET}", "context": {"secret_key": "k", "n": 1}},
        ]


async def test_results_are_redacted_and_report_it():
    registry = ToolRegistry(adapters=[LeakyLogs()], redactor=Redactor([SECRET]))
    result = await call("logs", {**BASE, **RANGE}, registry)
    text = json.dumps(result.structured_content) + result.content[0].text
    assert SECRET not in text and "hunter2" not in text
    assert result.structured_content["redacted"] is True
    assert result.structured_content["redaction_count"] >= 3


def test_clean_results_report_no_redaction():
    out = ToolRegistry(redactor=Redactor()).call_tool("dependencies", BASE)
    assert out["structuredContent"]["redacted"] is False


def test_error_messages_never_contain_secrets():
    registry = ToolRegistry(redactor=Redactor([SECRET]))
    for out in (
        registry.call_tool(f"no-such-{SECRET}", {}),
        registry.call_tool("logs", {**BASE, **RANGE, "bogus": SECRET}),
        registry.call_tool("logs", {"service": SECRET, "environment": "production"}),
    ):
        assert out["isError"] and SECRET not in json.dumps(out)


def test_secrets_loaded_from_settings(monkeypatch):
    monkeypatch.setenv("INCIDENTIQ_TOOL_REDACT_VALUES", f"{SECRET}, other-secret")
    out, _ = Redactor.from_settings().redact("a other-secret b")
    assert out == f"a {REDACTED} b"


def test_error_results_keep_transport_discriminators():
    from app.investigation_tools.redaction import Redactor
    from app.investigation_tools.mcp import _error

    redactor = Redactor(["text", "error"])
    result = _error("boom text", {"error": "timeout", "source": "logs"})
    from app.investigation_tools import mcp as m
    server = m.ToolRegistry.__new__(m.ToolRegistry)
    server._redactor = redactor
    server._call_tool = lambda *a, **k: result
    out = server.call_tool("x")
    assert out["content"][0]["type"] == "text"
    assert out["isError"] is True
    assert out["structuredContent"]["error"] == "timeout"
