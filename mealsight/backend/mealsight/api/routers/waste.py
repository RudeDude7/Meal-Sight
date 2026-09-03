"""POST/GET /api/waste — thin proxies onto pantry_manager's own
log_waste/get_waste_stats tools through the shared MCPClientManager. No
direct database access here, matching every other router in this
package; every response is exactly what the MCP tool itself returned
(translated through mealsight.api.mcp_proxy for error shapes).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/waste", tags=["waste"])


class LogWasteRequest(BaseModel):
    item_name: str
    quantity_wasted: float
    unit: str | None = None
    reason: str


@router.post("")
async def log_waste(body: LogWasteRequest, manager: MCPManagerDep) -> dict[str, Any]:
    result = await manager.call_tool(
        "pantry_manager",
        "log_waste",
        {
            "item_name": body.item_name,
            "quantity_wasted": body.quantity_wasted,
            "unit": body.unit,
            "reason": body.reason,
        },
    )
    return unwrap_mcp_result(result)


@router.get("")
async def get_waste_stats(manager: MCPManagerDep, time_range: str = "this_week") -> dict[str, Any]:
    result = await manager.call_tool("pantry_manager", "get_waste_stats", {"time_range": time_range})
    return unwrap_mcp_result(result)
