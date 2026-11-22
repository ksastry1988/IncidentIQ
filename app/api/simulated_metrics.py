import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.simulated_metrics.source import (
    MetricsComparison,
    MetricsQuery,
    SimulatedMetricsSource,
    SimulatedMetricsSourceError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/simulated", tags=["simulated metrics"])


def get_metrics_source() -> SimulatedMetricsSource:
    return SimulatedMetricsSource()


@router.get(
    "/metrics",
    response_model=MetricsComparison,
    responses={503: {"description": "Simulated metrics source unavailable"}},
)
def query_metrics(
    query: Annotated[MetricsQuery, Query()],
    source: Annotated[SimulatedMetricsSource, Depends(get_metrics_source)],
) -> MetricsComparison:
    try:
        return source.query(query)
    except SimulatedMetricsSourceError:
        logger.exception("Simulated metrics query failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "simulated_metrics_source_unavailable",
                "message": "The simulated metrics source is unavailable.",
            },
        ) from None
