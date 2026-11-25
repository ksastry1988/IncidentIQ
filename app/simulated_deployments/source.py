from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

DEFAULT_LOOKBACK_MINUTES = 1440
MAX_LOOKBACK_MINUTES = 10080


class DeploymentStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class Deployment(BaseModel):
    model_config = ConfigDict(frozen=True)

    deployment_id: str
    service: str
    environment: str = Field(default="production", exclude=True)
    version: str
    timestamp: AwareDatetime
    status: DeploymentStatus
    change_summary: str


class DeploymentQuery(BaseModel):
    service: str = Field(min_length=1, max_length=255)
    environment: str = Field(default="production", min_length=1, max_length=255)
    # End of the lookback window, typically the incident time.
    as_of: AwareDatetime
    lookback_minutes: int = Field(
        default=DEFAULT_LOOKBACK_MINUTES, ge=1, le=MAX_LOOKBACK_MINUTES
    )


class DeploymentHistory(BaseModel):
    service: str
    start: AwareDatetime
    end: AwareDatetime
    deployment_count: int = Field(ge=0)
    # False when the source holds no deployment records at all for the service.
    service_known: bool
    deployments: list[Deployment]


class SimulatedDeploymentSourceError(Exception):
    """The simulated deployment source is unavailable."""


def _deployment(
    deployment_id: str,
    service: str,
    version: str,
    day: int,
    hour: int,
    minute: int,
    status: DeploymentStatus,
    change_summary: str,
) -> Deployment:
    return Deployment(
        deployment_id=deployment_id,
        service=service,
        version=version,
        timestamp=datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc),
        status=status,
        change_summary=change_summary,
    )


S = DeploymentStatus

DEPLOYMENTS = (
    _deployment("dep-1001", "payments", "v2.13.0", 16, 15, 0, S.SUCCEEDED,
                "Upgrade payment gateway client library"),
    _deployment("dep-1002", "payments", "v2.14.0", 17, 11, 55, S.SUCCEEDED,
                "Reduce connection pool size and add synchronous fraud-check call"),
    _deployment("dep-1003", "payments", "v2.14.1", 17, 12, 30, S.ROLLED_BACK,
                "Hotfix for fraud-check timeout; rolled back to v2.13.0"),
    _deployment("dep-2001", "checkout", "v5.8.2", 17, 9, 30, S.SUCCEEDED,
                "Update cart totals rounding"),
    _deployment("dep-2002", "checkout", "v5.9.0", 17, 10, 45, S.FAILED,
                "Enable new shipping estimate flow; migration step failed"),
    _deployment("dep-3001", "search", "v1.40.0", 17, 8, 0, S.SUCCEEDED,
                "Add query suggestions index"),
)


class SimulatedDeploymentSource:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    def query(self, query: DeploymentQuery) -> DeploymentHistory:
        if self.unavailable:
            raise SimulatedDeploymentSourceError(
                "Simulated deployment source is unavailable"
            )

        start = query.as_of - timedelta(minutes=query.lookback_minutes)
        deployments = sorted(
            (
                deployment
                for deployment in DEPLOYMENTS
                if deployment.service == query.service
                and deployment.environment == query.environment
                and start <= deployment.timestamp <= query.as_of
            ),
            key=lambda deployment: (deployment.timestamp, deployment.deployment_id),
        )
        return DeploymentHistory(
            service=query.service,
            start=start,
            end=query.as_of,
            deployment_count=len(deployments),
            service_known=any(
                d.service == query.service and d.environment == query.environment
                for d in DEPLOYMENTS
            ),
            deployments=deployments,
        )
