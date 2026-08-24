"""The user-intelligence MCP server — a thin FastMCP transport shell over
mealsight.user_intelligence. Run with
`python -m mealsight.mcp_servers.user_intelligence` (stdio transport)."""

from mealsight.mcp_servers.user_intelligence.server import mcp

__all__ = ["mcp"]
