"""GET /api/history — a thin proxy onto user_intelligence's own
get_meal_history tool through the shared MCPClientManager.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
async def get_history(
    manager: MCPManagerDep,
    days_back: int = 14,
    cuisine_filter: str | None = None,
    rating_filter: int | None = None,
) -> dict[str, Any]:
    arguments = {"days_back": days_back, "cuisine_filter": cuisine_filter, "rating_filter": rating_filter}
    result = await manager.call_tool("user_intelligence", "get_meal_history", arguments)
    return unwrap_mcp_result(result)
