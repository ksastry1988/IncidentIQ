from datetime import datetime, timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class MetricsQuery(BaseModel):
    service: str = Field(min_length=1, max_length=255)
    environment: str = Field(default="production", min_length=1, max_length=255)
    incident_start: AwareDatetime
    incident_end: AwareDatetime
    baseline_start: AwareDatetime
    baseline_end: AwareDatetime

    @model_validator(mode="after")
    def validate_time_ranges(self) -> "MetricsQuery":
        if self.incident_start > self.incident_end:
            raise ValueError("incident_start must be earlier than or equal to incident_end")
        if self.baseline_start > self.baseline_end:
            raise ValueError("baseline_start must be earlier than or equal to baseline_end")
        return self


class MetricSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: str
    environment: str = Field(default="production", exclude=True)
    timestamp: AwareDatetime
    request_volume: int = Field(ge=0)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    p99_latency_ms: float = Field(ge=0)
    error_rate: float = Field(ge=0, le=100)
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)


class MetricsWindow(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    sample_count: int = Field(ge=0)
    data_available: bool
    request_volume: int | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    error_rate: float | None
    cpu_percent: float | None
    memory_percent: float | None


class MetricChange(BaseModel):
    absolute: float
    # None when the baseline value is zero.
    percent: float | None


class MetricsComparison(BaseModel):
    service: str
    incident: MetricsWindow
    baseline: MetricsWindow
    # Incident minus baseline per metric; empty when either window has no data.
    change: dict[str, MetricChange]


COMPARED_METRICS = (
    "request_volume",
    "p50_latency_ms",
    "p95_latency_ms",
    "p99_latency_ms",
    "error_rate",
    "cpu_percent",
    "memory_percent",
)


def _compare(incident: MetricsWindow, baseline: MetricsWindow) -> dict[str, MetricChange]:
    if not (incident.data_available and baseline.data_available):
        return {}
    change = {}
    for name in COMPARED_METRICS:
        now, before = getattr(incident, name), getattr(baseline, name)
        change[name] = MetricChange(
            absolute=now - before,
            percent=(now - before) / before * 100 if before else None,
        )
    return change


class SimulatedMetricsSourceError(Exception):
    """The simulated metrics source is unavailable."""


def _sample(
    service: str,
    hour: int,
    minute: int,
    request_volume: int,
    p50_latency_ms: float,
    p95_latency_ms: float,
    p99_latency_ms: float,
    error_rate: float,
    cpu_percent: float,
    memory_percent: float,
) -> MetricSample:
    return MetricSample(
        service=service,
        timestamp=datetime(2026, 11, 17, hour, minute, tzinfo=timezone.utc),
        request_volume=request_volume,
        p50_latency_ms=p50_latency_ms,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        error_rate=error_rate,
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
    )


SAMPLES = (
    _sample("payments", 11, 45, 100, 80, 150, 250, 0.5, 45, 60),
    _sample("payments", 11, 50, 105, 82, 155, 260, 0.4, 46, 61),
    _sample("payments", 12, 0, 120, 300, 1200, 2500, 8.0, 52, 65),
    _sample("payments", 12, 5, 125, 320, 1300, 2800, 9.0, 54, 66),
    _sample("checkout", 12, 50, 200, 50, 100, 180, 0.2, 40, 55),
    _sample("checkout", 12, 55, 205, 52, 105, 190, 0.2, 41, 55),
    _sample("checkout", 13, 0, 190, 500, 1800, 3200, 3.0, 43, 56),
    _sample("checkout", 13, 5, 195, 550, 2000, 3500, 3.5, 44, 56),
    _sample("search", 13, 50, 300, 40, 90, 150, 0.1, 35, 50),
    _sample("search", 13, 55, 310, 42, 95, 160, 0.1, 36, 51),
    _sample("search", 14, 0, 280, 180, 900, 1800, 2.0, 98, 92),
    _sample("search", 14, 5, 275, 220, 1100, 2200, 4.0, 99, 94),
)


class SimulatedMetricsSource:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    def query(self, query: MetricsQuery) -> MetricsComparison:
        if self.unavailable:
            raise SimulatedMetricsSourceError("Simulated metrics source is unavailable")

        service_samples = [
            sample
            for sample in SAMPLES
            if sample.service == query.service and sample.environment == query.environment
        ]
        incident = self._window(
            service_samples, query.incident_start, query.incident_end
        )
        baseline = self._window(
            service_samples, query.baseline_start, query.baseline_end
        )
        return MetricsComparison(
            service=query.service,
            incident=incident,
            baseline=baseline,
            change=_compare(incident, baseline),
        )

    @staticmethod
    def _window(
        samples: list[MetricSample], start: datetime, end: datetime
    ) -> MetricsWindow:
        selected = [
            sample for sample in samples if start <= sample.timestamp <= end
        ]
        if not selected:
            return MetricsWindow(
                start=start,
                end=end,
                sample_count=0,
                data_available=False,
                request_volume=None,
                p50_latency_ms=None,
                p95_latency_ms=None,
                p99_latency_ms=None,
                error_rate=None,
                cpu_percent=None,
                memory_percent=None,
            )

        def average(field: str) -> float:
            return sum(getattr(sample, field) for sample in selected) / len(selected)

        return MetricsWindow(
            start=start,
            end=end,
            sample_count=len(selected),
            data_available=True,
            request_volume=sum(sample.request_volume for sample in selected),
            p50_latency_ms=average("p50_latency_ms"),
            p95_latency_ms=average("p95_latency_ms"),
            p99_latency_ms=average("p99_latency_ms"),
            error_rate=average("error_rate"),
            cpu_percent=average("cpu_percent"),
            memory_percent=average("memory_percent"),
        )
