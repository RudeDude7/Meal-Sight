"""GET /api/interactions — a thin proxy onto user_intelligence's own
get_interaction_history tool through the shared MCPClientManager.

Distinct from GET /api/history: that endpoint (mealsight.api.routers.
history) reads meal_history, which only ever gets a row on a CONFIRMED
cook (mealsight.api.routers.cook). This endpoint reads every
recommendation REQUEST and its outcome, regardless of whether anything
was ever cooked — the record a user with no login still gets to see
"everything I asked MealSight for," not just what they went on to
actually make.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/interactions", tags=["interactions"])


@router.get("")
async def get_interactions(
    manager: MCPManagerDep,
    days_back: int = 30,
    limit: int = 50,
) -> dict[str, Any]:
    arguments = {"days_back": days_back, "limit": limit}
    result = await manager.call_tool("user_intelligence", "get_interaction_history", arguments)
    return unwrap_mcp_result(result)
