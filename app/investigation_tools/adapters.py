from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Generic, Mapping, TypeVar

from app.investigation_tools.schemas import (
    DependenciesParams,
    DeploymentsParams,
    LogsParams,
    MetricsParams,
    ResultEnvelope,
    ToolLimits,
    ToolName,
    ToolParams,
)
from app.simulated_dependencies.source import DependencyQuery, SimulatedDependencySource
from app.simulated_deployments.source import DeploymentQuery, SimulatedDeploymentSource
from app.simulated_logs.source import LogQuery, LogSeverity, SimulatedLogSource
from app.simulated_metrics.source import MetricsQuery, SimulatedMetricsSource

P = TypeVar("P", bound=ToolParams)


class ToolAdapter(ABC, Generic[P]):
    """Read-only adapter: validates parameters, queries a source, returns an envelope."""

    tool: ClassVar[ToolName]
    params_model: ClassVar[type[ToolParams]]
    source_name: ClassVar[str]

    def __init__(self, limits: ToolLimits | None = None) -> None:
        self.limits = limits or ToolLimits()

    def input_schema(self) -> dict[str, Any]:
        return self.params_model.model_json_schema()

    def execute(self, arguments: Mapping[str, Any]) -> ResultEnvelope:
        """Raises pydantic.ValidationError for missing or out-of-bounds parameters."""
        params: P = self.params_model.model_validate(  # type: ignore[assignment]
            arguments, context={"limits": self.limits}
        )
        items = self.fetch(params)
        limit = params.limit  # type: ignore[attr-defined]
        return ResultEnvelope(
            source=self.source_name,
            tool=self.tool,
            service=params.service,
            environment=params.environment,
            query=params.model_dump(mode="json", exclude_none=True),
            items=items[:limit],
            truncated=len(items) > limit,
            retrieved_at=datetime.now(timezone.utc),
        )

    @abstractmethod
    def fetch(self, params: P) -> list[dict[str, Any]]:
        """Return all matching items as JSON-compatible dicts; the limit is applied by `execute`."""


class LogsAdapter(ToolAdapter[LogsParams]):
    tool = ToolName.LOGS
    params_model = LogsParams
    source_name = "simulated-logs"

    def __init__(self, source: SimulatedLogSource | None = None, limits: ToolLimits | None = None) -> None:
        super().__init__(limits)
        self.source = source or SimulatedLogSource()

    def fetch(self, params: LogsParams) -> list[dict[str, Any]]:
        query = LogQuery(
            service=params.service,
            environment=params.environment,
            start=params.start,
            end=params.end,
            severity=LogSeverity(params.severity.upper()) if params.severity else None,
            error_pattern=params.error_pattern,
            correlation_id=params.correlation_id,
            page_size=100,
        )
        items: list[dict[str, Any]] = []
        while True:
            page = self.source.query(query)
            items.extend(e.model_dump(mode="json") for e in page.items)
            # Stop once one item past the limit is known, enough to flag truncation.
            if not page.has_more or len(items) > params.limit:  # type: ignore[operator]
                return items
            query = query.model_copy(update={"page": query.page + 1})


class MetricsAdapter(ToolAdapter[MetricsParams]):
    tool = ToolName.METRICS
    params_model = MetricsParams
    source_name = "simulated-metrics"

    def __init__(self, source: SimulatedMetricsSource | None = None, limits: ToolLimits | None = None) -> None:
        super().__init__(limits)
        self.source = source or SimulatedMetricsSource()

    def fetch(self, params: MetricsParams) -> list[dict[str, Any]]:
        span: timedelta = params.end - params.start
        comparison = self.source.query(
            MetricsQuery(
                service=params.service,
                environment=params.environment,
                incident_start=params.start,
                incident_end=params.end,
                baseline_start=params.start - span,
                baseline_end=params.start,
            )
        )
        return [
            {"window": "incident", **comparison.incident.model_dump(mode="json")},
            {"window": "baseline", **comparison.baseline.model_dump(mode="json")},
        ]


class DeploymentsAdapter(ToolAdapter[DeploymentsParams]):
    tool = ToolName.DEPLOYMENTS
    params_model = DeploymentsParams
    source_name = "simulated-deployments"

    def __init__(self, source: SimulatedDeploymentSource | None = None, limits: ToolLimits | None = None) -> None:
        super().__init__(limits)
        self.source = source or SimulatedDeploymentSource()

    def fetch(self, params: DeploymentsParams) -> list[dict[str, Any]]:
        span_minutes = max(1, -(-int((params.end - params.start).total_seconds()) // 60))
        history = self.source.query(
            DeploymentQuery(
                service=params.service,
                environment=params.environment,
                as_of=params.end,
                lookback_minutes=span_minutes,
            )
        )
        return [
            d.model_dump(mode="json")
            for d in history.deployments
            if d.timestamp >= params.start
        ]


class DependenciesAdapter(ToolAdapter[DependenciesParams]):
    tool = ToolName.DEPENDENCIES
    params_model = DependenciesParams
    source_name = "simulated-dependencies"

    def __init__(self, source: SimulatedDependencySource | None = None, limits: ToolLimits | None = None) -> None:
        super().__init__(limits)
        self.source = source or SimulatedDependencySource()

    def fetch(self, params: DependenciesParams) -> list[dict[str, Any]]:
        result = self.source.query(
            DependencyQuery(service=params.service, environment=params.environment)
        )
        return [r.model_dump(mode="json") for r in result.relationships]
