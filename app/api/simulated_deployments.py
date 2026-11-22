import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.simulated_deployments.source import (
    DeploymentHistory,
    DeploymentQuery,
    SimulatedDeploymentSource,
    SimulatedDeploymentSourceError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/simulated", tags=["simulated deployments"])


def get_deployment_source() -> SimulatedDeploymentSource:
    return SimulatedDeploymentSource()


@router.get(
    "/deployments",
    response_model=DeploymentHistory,
    responses={503: {"description": "Simulated deployment source unavailable"}},
)
def query_deployments(
    query: Annotated[DeploymentQuery, Query()],
    source: Annotated[SimulatedDeploymentSource, Depends(get_deployment_source)],
) -> DeploymentHistory:
    try:
        return source.query(query)
    except SimulatedDeploymentSourceError:
        logger.exception("Simulated deployment query failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "simulated_deployment_source_unavailable",
                "message": "The simulated deployment source is unavailable.",
            },
        ) from None
