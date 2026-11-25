"""Authorization of investigation tool calls by service and environment."""
import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from app.config import ToolAccessSettings

logger = logging.getLogger(__name__)

ACCESS_DENIED = "access_denied"


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _parse(raw: str) -> list[str]:
    return [v.strip() for v in raw.split(",") if v.strip()]


@dataclass(frozen=True)
class AccessDenied(Exception):
    """`field` names the rejected argument; the rejected value is never carried."""

    field: str


class AccessPolicy:
    """Allow-list of services and environments. An empty list allows nothing."""

    def __init__(self, services: Iterable[str], environments: Iterable[str]) -> None:
        self._services = {_normalize(s): s for s in services}
        self._environments = {_normalize(e): e for e in environments}

    @classmethod
    def from_settings(cls, settings: ToolAccessSettings | None = None) -> "AccessPolicy":
        settings = settings or ToolAccessSettings()
        return cls(
            _parse(settings.tool_allowed_services),
            _parse(settings.tool_allowed_environments),
        )

    def authorize(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Return the arguments with service/environment replaced by their canonical
        allowed spelling, so the value checked is the value queried.

        Absent values pass through so schema validation reports them.
        Raises AccessDenied for any value that is not an allowed string.
        """
        checked = dict(arguments)
        for field, allowed in (("service", self._services), ("environment", self._environments)):
            if field not in checked:
                continue
            value = checked[field]
            canonical = allowed.get(_normalize(value)) if isinstance(value, str) else None
            if canonical is None:
                raise AccessDenied(field)
            checked[field] = canonical
        return checked
