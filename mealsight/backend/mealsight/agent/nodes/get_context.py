"""get_context — STUB (mealsight.agent.nodes._common.run_stub).

Will gather the grounding data everything downstream reasons against:
get_pantry and flag_expiring from pantry_manager (-> pantry_items,
expiring_items), get_user_profile and get_context_signals from
user_intelligence (-> user_profile, context_signals), and get_meal_
history from user_intelligence (-> meal_history) — all through
mealsight.agent.mcp_client.MCPClientManager.call_tool, and plausibly
concurrently, since none of these five calls actually depends on any
of the others' results.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "get_context"
DESCRIPTION = (
    "Will fetch pantry contents, expiring items, user profile, context signals, and "
    "meal history from the pantry_manager/user_intelligence MCP servers."
)


async def get_context(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
