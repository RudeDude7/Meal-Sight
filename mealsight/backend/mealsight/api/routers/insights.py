"""GET /api/insights — a thin proxy onto user_intelligence's own
get_taste_insights tool through the shared MCPClientManager.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("")
async def get_taste_insights(manager: MCPManagerDep, time_range: str = "this_month") -> dict[str, Any]:
    result = await manager.call_tool("user_intelligence", "get_taste_insights", {"time_range": time_range})
    return unwrap_mcp_result(result)
