"""MCP server exposing the read-only investigation tools over stdio.

Run with `python -m app.investigation_tools.server`.
"""
from typing import Any

import anyio
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from app.investigation_tools.mcp import ToolRegistry


def create_server(registry: ToolRegistry | None = None) -> Server:
    registry = registry or ToolRegistry()

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult.model_validate({"tools": registry.list_tools()})

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        return types.CallToolResult.model_validate(registry.call_tool(params.name, params.arguments))

    return Server("incidentiq-investigation-tools", on_list_tools=list_tools, on_call_tool=call_tool)


async def _serve() -> None:
    server = create_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_serve)
