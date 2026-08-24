"""The recipe-engine MCP server — a thin FastMCP transport shell over
mealsight.recipe_engine and mealsight.matching. Run with
`python -m mealsight.mcp_servers.recipe_engine` (stdio transport)."""

from mealsight.mcp_servers.recipe_engine.server import mcp

__all__ = ["mcp"]
