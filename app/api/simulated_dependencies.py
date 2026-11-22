import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.simulated_dependencies.source import (
    DependencyQuery,
    ServiceDependencies,
    SimulatedDependencySource,
    SimulatedDependencySourceError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/simulated", tags=["simulated dependencies"])


def get_dependency_source() -> SimulatedDependencySource:
    return SimulatedDependencySource()


@router.get(
    "/dependencies",
    response_model=ServiceDependencies,
    responses={503: {"description": "Simulated dependency source unavailable"}},
)
def query_dependencies(
    query: Annotated[DependencyQuery, Query()],
    source: Annotated[SimulatedDependencySource, Depends(get_dependency_source)],
) -> ServiceDependencies:
    try:
        return source.query(query)
    except SimulatedDependencySourceError:
        logger.exception("Simulated dependency query failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "simulated_dependency_source_unavailable",
                "message": "The simulated dependency source is unavailable.",
            },
        ) from None
