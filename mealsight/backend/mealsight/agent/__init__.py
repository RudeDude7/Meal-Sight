"""The MealSight agent: MCPClientManager (mealsight.agent.mcp_client)
owns the three MCP server subprocesses for the lifetime of one
recommendation; MealSightState (mealsight.agent.state) is the
LangGraph state schema; build_graph (mealsight.agent.graph) wires the
eleven-node pipeline (every node a stub in this phase — see mealsight.
agent.nodes); run_recommendation (mealsight.agent.runner) is the single
entry point tying all three together.
"""

from mealsight.agent.graph import NODE_ORDER, build_graph
from mealsight.agent.mcp_client import (
    EXPECTED_TOOLS,
    MCPClientManager,
    MCPServerStartupError,
    ServerName,
    ToolCallResult,
)
from mealsight.agent.runner import run_recommendation
from mealsight.agent.state import MealSightState

__all__ = [
    "EXPECTED_TOOLS",
    "NODE_ORDER",
    "MCPClientManager",
    "MCPServerStartupError",
    "MealSightState",
    "ServerName",
    "ToolCallResult",
    "build_graph",
    "run_recommendation",
]
