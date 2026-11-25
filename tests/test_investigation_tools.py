from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.investigation_tools import (
    DependenciesAdapter,
    DeploymentsAdapter,
    LogsAdapter,
    MetricsAdapter,
    ToolLimits,
)

RANGE = {"start": "2026-11-17T11:00:00Z", "end": "2026-11-17T13:00:00Z"}
BASE = {"service": "payments", "environment": "production"}
ENVELOPE_KEYS = {
    "source", "tool", "service", "environment", "query", "items", "truncated", "retrieved_at",
}

TIMED = [LogsAdapter, MetricsAdapter, DeploymentsAdapter]
ALL = [*TIMED, DependenciesAdapter]


@pytest.mark.parametrize("adapter_cls", ALL)
def test_envelope_shape(adapter_cls):
    args = BASE if adapter_cls is DependenciesAdapter else {**BASE, **RANGE}
    result = adapter_cls().execute(args).model_dump(mode="json")
    assert set(result) == ENVELOPE_KEYS
    assert result["tool"] == adapter_cls.tool.value
    assert result["service"] == "payments"
    assert result["environment"] == "production"
    assert result["retrieved_at"].endswith("Z")


def test_logs_return_items():
    result = LogsAdapter().execute({**BASE, **RANGE})
    assert len(result.items) == 3
    assert result.truncated is False


@pytest.mark.parametrize("adapter_cls", ALL)
@pytest.mark.parametrize("missing", ["service", "environment"])
def test_missing_required(adapter_cls, missing):
    args = {**BASE, **RANGE}
    del args[missing]
    with pytest.raises(ValidationError):
        adapter_cls().execute(args)


@pytest.mark.parametrize("adapter_cls", TIMED)
@pytest.mark.parametrize("missing", ["start", "end"])
def test_missing_time_range(adapter_cls, missing):
    args = {**BASE, **RANGE}
    del args[missing]
    with pytest.raises(ValidationError):
        adapter_cls().execute(args)


@pytest.mark.parametrize("adapter_cls", TIMED)
def test_invalid_time_ranges(adapter_cls):
    adapter = adapter_cls(limits=ToolLimits(max_time_range=timedelta(hours=3)))
    with pytest.raises(ValidationError, match="earlier than start"):
        adapter.execute({**BASE, "start": RANGE["end"], "end": RANGE["start"]})
    with pytest.raises(ValidationError, match="must not exceed"):
        adapter.execute({**BASE, "start": "2026-11-17T00:00:00Z", "end": "2026-11-17T04:00:00Z"})
    with pytest.raises(ValidationError):  # naive datetimes are not timezone-aware
        adapter.execute({**BASE, "start": "2026-11-17T11:00:00", "end": "2026-11-17T12:00:00"})


@pytest.mark.parametrize("adapter_cls", ALL)
def test_limit_bounds(adapter_cls):
    args = BASE if adapter_cls is DependenciesAdapter else {**BASE, **RANGE}
    adapter = adapter_cls(limits=ToolLimits(default_limit=5, max_limit=10))
    assert adapter.execute(args).query["limit"] == 5
    for bad in (11, 0):
        with pytest.raises(ValidationError):
            adapter.execute({**args, "limit": bad})


def test_results_never_exceed_limit_and_flag_truncation():
    result = LogsAdapter().execute({**BASE, **RANGE, "limit": 2})
    assert len(result.items) == 2
    assert result.truncated is True

    deps = DependenciesAdapter().execute({"service": "checkout", "environment": "production", "limit": 1})
    assert len(deps.items) == 1
    assert deps.truncated is True


def test_metrics_items_cover_both_windows():
    result = MetricsAdapter().execute({**BASE, **RANGE})
    assert [i["window"] for i in result.items] == ["incident", "baseline"]


def test_deployments_in_range():
    result = DeploymentsAdapter().execute({**BASE, **RANGE})
    assert all(
        RANGE["start"] <= i["timestamp"].replace("+00:00", "Z") <= RANGE["end"]
        for i in result.items
    )
