from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationInfo, model_validator


class ToolName(str, Enum):
    LOGS = "logs"
    METRICS = "metrics"
    DEPLOYMENTS = "deployments"
    DEPENDENCIES = "dependencies"


class ToolLimits(BaseModel):
    """Configurable bounds applied while validating tool parameters."""

    model_config = ConfigDict(frozen=True)

    max_time_range: timedelta = timedelta(hours=24)
    default_limit: int = Field(default=50, ge=1)
    max_limit: int = Field(default=200, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "ToolLimits":
        if self.max_time_range <= timedelta(0):
            raise ValueError("max_time_range must be positive")
        if self.default_limit > self.max_limit:
            raise ValueError("default_limit must not exceed max_limit")
        return self


class ToolParams(BaseModel):
    """Parameters shared by every tool. Validate with `model_validate(data, context={"limits": ToolLimits(...)})`."""

    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1, max_length=255)
    environment: str = Field(min_length=1, max_length=255)


class TimeRangeParams(ToolParams):
    start: AwareDatetime
    end: AwareDatetime
    limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_range_and_limit(self, info: ValidationInfo) -> "TimeRangeParams":
        limits = _limits(info)
        if self.end < self.start:
            raise ValueError("end must not be earlier than start")
        if self.end - self.start > limits.max_time_range:
            raise ValueError(
                f"time range must not exceed {limits.max_time_range}"
            )
        self.limit = _resolve_limit(self.limit, limits)
        return self


class LogsParams(TimeRangeParams):
    severity: str | None = Field(default=None, min_length=1, max_length=32)
    error_pattern: str | None = Field(default=None, min_length=1, max_length=255)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=255)


class MetricsParams(TimeRangeParams):
    """Compares the requested window with the equal-length window preceding it."""


class DeploymentsParams(TimeRangeParams):
    pass


class DependenciesParams(ToolParams):
    limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_limit(self, info: ValidationInfo) -> "DependenciesParams":
        self.limit = _resolve_limit(self.limit, _limits(info))
        return self


class ResultEnvelope(BaseModel):
    source: str
    tool: ToolName
    service: str
    environment: str
    query: dict[str, Any]
    items: list[dict[str, Any]]
    truncated: bool
    retrieved_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _limits(info: ValidationInfo) -> ToolLimits:
    context = info.context or {}
    return context.get("limits") or ToolLimits()


def _resolve_limit(limit: int | None, limits: ToolLimits) -> int:
    if limit is None:
        return limits.default_limit
    if limit > limits.max_limit:
        raise ValueError(f"limit must not exceed {limits.max_limit}")
    return limit
