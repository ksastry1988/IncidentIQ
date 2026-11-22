"""Deterministic simulated service dependency data source."""
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RelationshipDirection(str, Enum):
    # The requested service calls / relies on the related service.
    DEPENDS_ON = "depends_on"
    # The related service calls / relies on the requested service.
    DEPENDED_ON_BY = "depended_on_by"


class DependencyQuery(BaseModel):
    service: str = Field(min_length=1, max_length=255)


class ServiceRelationship(BaseModel):
    service: str
    direction: RelationshipDirection
    # 1 for a direct relationship, higher for transitive ones.
    depth: int = Field(ge=1)
    # Call path from the caller to the callee, e.g. ["checkout", "inventory"].
    path: list[str]


class ServiceDependencies(BaseModel):
    service: str
    relationship_count: int = Field(ge=0)
    relationships: list[ServiceRelationship]


class SimulatedDependencySourceError(Exception):
    """The simulated dependency source is unavailable."""


# (caller, callee) edges.
DEPENDENCY_EDGES = (
    ("checkout", "payments"),
    ("checkout", "inventory"),
    ("payments", "fraud-check"),
    ("inventory", "inventory-db"),
    ("search", "search-index"),
)


def _walk(service: str, direction: RelationshipDirection) -> list[ServiceRelationship]:
    downward = direction is RelationshipDirection.DEPENDS_ON
    results: list[ServiceRelationship] = []
    queue = [[service]]
    while queue:
        path = queue.pop(0)
        for caller, callee in sorted(DEPENDENCY_EDGES):
            current, nxt = (caller, callee) if downward else (callee, caller)
            if current != path[-1] or nxt in path:
                continue
            new_path = [*path, nxt]
            queue.append(new_path)
            results.append(
                ServiceRelationship(
                    service=nxt,
                    direction=direction,
                    depth=len(new_path) - 1,
                    path=new_path if downward else new_path[::-1],
                )
            )
    return results


class SimulatedDependencySource:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    def query(self, query: DependencyQuery) -> ServiceDependencies:
        if self.unavailable:
            raise SimulatedDependencySourceError(
                "Simulated dependency source is unavailable"
            )

        relationships = sorted(
            (
                *_walk(query.service, RelationshipDirection.DEPENDS_ON),
                *_walk(query.service, RelationshipDirection.DEPENDED_ON_BY),
            ),
            key=lambda r: (r.direction.value, r.depth, r.service),
        )
        return ServiceDependencies(
            service=query.service,
            relationship_count=len(relationships),
            relationships=relationships,
        )
