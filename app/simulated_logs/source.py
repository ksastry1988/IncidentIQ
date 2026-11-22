from datetime import datetime, timezone
from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class LogSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    service: str
    timestamp: AwareDatetime
    severity: LogSeverity
    message: str
    correlation_id: str


class LogQuery(BaseModel):
    service: str = Field(min_length=1, max_length=255)
    start: AwareDatetime
    end: AwareDatetime
    severity: LogSeverity | None = None
    error_pattern: str | None = Field(default=None, min_length=1, max_length=255)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=255)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @model_validator(mode="after")
    def validate_time_range(self) -> "LogQuery":
        if self.start > self.end:
            raise ValueError("start must be earlier than or equal to end")
        return self


class LogPage(BaseModel):
    items: list[LogEvent]
    page: int
    page_size: int
    has_more: bool
    # False when the source holds no logs at all for the requested service.
    service_known: bool


class SimulatedLogSourceError(Exception):
    """The simulated log source is unavailable."""


def _event(
    id: str,
    service: str,
    hour: int,
    minute: int,
    severity: LogSeverity,
    message: str,
    correlation_id: str,
) -> LogEvent:
    return LogEvent(
        id=id,
        service=service,
        timestamp=datetime(2026, 11, 17, hour, minute, tzinfo=timezone.utc),
        severity=severity,
        message=message,
        correlation_id=correlation_id,
    )


EVENTS = (
    _event("deploy-001", "payments", 11, 55, LogSeverity.INFO,
           "Version 2.4.0 deployed to payments", "deploy-240"),
    _event("deploy-002", "payments", 12, 0, LogSeverity.ERROR,
           "Payment request failed after deployment: invalid configuration", "pay-101"),
    _event("deploy-003", "payments", 12, 1, LogSeverity.ERROR,
           "Payment request failed after deployment: invalid configuration", "pay-102"),
    _event("downstream-001", "checkout", 13, 0, LogSeverity.ERROR,
           "Request to inventory timed out", "checkout-201"),
    _event("downstream-002", "inventory", 13, 0, LogSeverity.WARNING,
           "Inventory database response is slow", "checkout-201"),
    _event("downstream-003", "checkout", 13, 1, LogSeverity.ERROR,
           "Request to inventory timed out", "checkout-202"),
    _event("resource-001", "search", 14, 0, LogSeverity.WARNING,
           "CPU utilization at 98 percent; request queue growing", "search-301"),
    _event("resource-002", "search", 14, 1, LogSeverity.ERROR,
           "Request rejected: worker pool exhausted", "search-302"),
)


class SimulatedLogSource:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    def query(self, query: LogQuery) -> LogPage:
        if self.unavailable:
            raise SimulatedLogSourceError("Simulated log source is unavailable")

        matches = sorted(
            (
                event
                for event in EVENTS
                if event.service == query.service
                and query.start <= event.timestamp <= query.end
                and (query.severity is None or event.severity == query.severity)
                and (
                    query.error_pattern is None
                    or query.error_pattern.casefold() in event.message.casefold()
                )
                and (
                    query.correlation_id is None
                    or event.correlation_id == query.correlation_id
                )
            ),
            key=lambda event: (event.timestamp, event.id),
        )
        offset = (query.page - 1) * query.page_size
        return LogPage(
            items=matches[offset : offset + query.page_size],
            page=query.page,
            page_size=query.page_size,
            has_more=offset + query.page_size < len(matches),
            service_known=any(e.service == query.service for e in EVENTS),
        )
