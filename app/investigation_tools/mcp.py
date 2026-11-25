"""MCP-facing layer: tool descriptors and a call dispatcher.

Shapes follow the MCP `tools/list` and `tools/call` results so a server (or test)
can use them directly without this module depending on an MCP SDK.
"""
import json
from typing import Any, Mapping

from pydantic import ValidationError

from app.investigation_tools.adapters import (
    DependenciesAdapter,
    DeploymentsAdapter,
    LogsAdapter,
    MetricsAdapter,
    ToolAdapter,
)
from app.investigation_tools.schemas import ToolLimits

DESCRIPTIONS = {
    "logs": "Read-only search of service logs within a time range.",
    "metrics": "Read-only metrics for a time range compared with the preceding equal-length baseline.",
    "deployments": "Read-only deployment history for a service within a time range.",
    "dependencies": "Read-only upstream and downstream dependencies of a service.",
}


class ToolRegistry:
    def __init__(self, adapters: list[ToolAdapter] | None = None, limits: ToolLimits | None = None) -> None:
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

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        adapter = self._adapters.get(name)
        if adapter is None:
            return _error(f"Unknown tool: {name}")
        try:
            envelope = adapter.execute(arguments or {})
        except ValidationError as exc:
            errors = [
                {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                for e in exc.errors()
            ]
            return _error("Invalid parameters", {"validation_errors": errors})
        structured = envelope.model_dump(mode="json")
        return {
            "content": [{"type": "text", "text": json.dumps(structured)}],
            "structuredContent": structured,
            "isError": False,
        }


def _error(message: str, structured: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": message}], "isError": True}
    if structured:
        result["structuredContent"] = structured
    return result
