"""The pantry-manager MCP server — a thin FastMCP transport shell over
mealsight.pantry. Run with `python -m mealsight.mcp_servers.pantry_manager`
(stdio transport)."""

from mealsight.mcp_servers.pantry_manager.server import mcp

__all__ = ["mcp"]
