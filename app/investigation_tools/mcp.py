"""MCP-facing layer: tool descriptors and a call dispatcher.

Shapes follow the MCP `tools/list` and `tools/call` results so a server (or test)
can use them directly without this module depending on an MCP SDK.
"""
import json
import logging
import threading
from typing import Any, Mapping

from pydantic import ValidationError

from app.investigation_tools.adapters import (
    DependenciesAdapter,
    DeploymentsAdapter,
    LogsAdapter,
    MetricsAdapter,
    ToolAdapter,
)
from app.config import ToolTimeoutSettings
from app.investigation_tools.access import ACCESS_DENIED, AccessDenied, AccessPolicy
from app.investigation_tools.schemas import ToolLimits

logger = logging.getLogger(__name__)

TIMEOUT = "timeout"
SOURCE_ERROR = "source_error"

DESCRIPTIONS = {
    "logs": "Read-only search of service logs within a time range.",
    "metrics": "Read-only metrics for a time range compared with the preceding equal-length baseline.",
    "deployments": "Read-only deployment history for a service within a time range.",
    "dependencies": "Read-only upstream and downstream dependencies of a service.",
}


class ToolRegistry:
    def __init__(
        self,
        adapters: list[ToolAdapter] | None = None,
        limits: ToolLimits | None = None,
        policy: AccessPolicy | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        if timeout_seconds is None:
            timeout_seconds = ToolTimeoutSettings().tool_timeout_seconds
        if not timeout_seconds > 0 or timeout_seconds == float("inf"):
            raise ValueError("timeout_seconds must be a positive, finite number")
        self._timeout = timeout_seconds
        self._policy = policy or AccessPolicy.from_settings()
        limits = limits or ToolLimits()
        adapters = adapters or [
            LogsAdapter(limits=limits),
            MetricsAdapter(limits=limits),
            DeploymentsAdapter(limits=limits),
            DependenciesAdapter(limits=limits),
        ]
        self._adapters = {a.tool.value: a for a in adapters}

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": DESCRIPTIONS[name],
                "inputSchema": adapter.input_schema(),
                "annotations": {"readOnlyHint": True},
            }
            for name, adapter in self._adapters.items()
        ]

    def _run(self, adapter: ToolAdapter, arguments: Mapping[str, Any]) -> Any:
        """Run the adapter on a worker thread and stop waiting after the timeout.

        A blocked synchronous source cannot be interrupted, so its daemon thread is
        abandoned and its late result discarded.
        """
        outcome: dict[str, Any] = {}

        def work() -> None:
            try:
                outcome["value"] = adapter.execute(arguments)
            except BaseException as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=work, name=f"tool-{adapter.tool.value}", daemon=True)
        worker.start()
        worker.join(self._timeout)
        if worker.is_alive():
            raise _TimedOut
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        adapter = self._adapters.get(name)
        if adapter is None:
            return _error(f"Unknown tool: {name}")
        try:
            checked = self._policy.authorize(arguments or {})
        except AccessDenied as denied:
            # Log the tool and rejected field only, never the submitted values.
            logger.warning("access denied: tool=%s field=%s", name, denied.field)
            return _error(
                f"Access denied: {denied.field} is not authorized",
                {"error": ACCESS_DENIED, "field": denied.field},
            )
        try:
            envelope = self._run(adapter, checked)
        except _TimedOut:
            logger.warning("tool timeout: tool=%s timeout=%ss", name, self._timeout)
            return _error(
                f"{adapter.source_name} timed out after {self._timeout:g}s",
                {"status": "error", "error": TIMEOUT, "source": adapter.source_name},
            )
        except ValidationError as exc:
            errors = [
                {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                for e in exc.errors()
            ]
            return _error("Invalid parameters", {"validation_errors": errors})
        except Exception as exc:
            # Log the failure server-side; the caller gets no traceback or internals.
            logger.error(
                "source error: tool=%s source=%s",
                name,
                adapter.source_name,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return _error(
                f"{adapter.source_name} is unavailable",
                {"status": "error", "error": SOURCE_ERROR, "source": adapter.source_name},
            )
        structured = envelope.model_dump(mode="json")
        return {
            "content": [{"type": "text", "text": json.dumps(structured)}],
            "structuredContent": structured,
            "isError": False,
        }


class _TimedOut(Exception):
    pass


def _error(message: str, structured: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": message}], "isError": True}
    if structured:
        result["structuredContent"] = structured
    return result
