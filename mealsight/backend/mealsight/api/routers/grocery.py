"""GET /api/grocery-list — a thin proxy onto pantry_manager's own
get_grocery_list tool through the shared MCPClientManager.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/grocery-list", tags=["grocery"])


@router.get("")
async def get_grocery_list(manager: MCPManagerDep, list_id: int | None = None) -> dict[str, Any]:
    result = await manager.call_tool("pantry_manager", "get_grocery_list", {"list_id": list_id})
    return unwrap_mcp_result(result)
