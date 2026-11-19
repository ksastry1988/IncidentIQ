import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.simulated_logs.source import (
    LogPage,
    LogQuery,
    SimulatedLogSource,
    SimulatedLogSourceError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/simulated", tags=["simulated logs"])


def get_log_source() -> SimulatedLogSource:
    return SimulatedLogSource()


@router.get(
    "/logs",
    response_model=LogPage,
    responses={503: {"description": "Simulated log source unavailable"}},
)
def query_logs(
    query: Annotated[LogQuery, Query()],
    source: Annotated[SimulatedLogSource, Depends(get_log_source)],
) -> LogPage:
    try:
        return source.query(query)
    except SimulatedLogSourceError:
        logger.exception("Simulated log query failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "simulated_log_source_unavailable",
                "message": "The simulated log source is unavailable.",
            },
        ) from None
