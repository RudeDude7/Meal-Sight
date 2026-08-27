"""GET /api/history — a thin proxy onto user_intelligence's own
get_meal_history tool through the shared MCPClientManager.

POST /api/history/{meal_id}/rate — rates (or re-rates) an
already-logged meal, via user_intelligence's own rate_meal tool. This
is genuinely the only tool that can do this: log_meal's own rating
parameter only ever applies at the moment a meal is first logged (see
mealsight.api.routers.cook, which passes rating straight into log_meal
for a meal being rated at cook time); this endpoint is for "I cooked
this a while ago and I'm rating it now" instead.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/history", tags=["history"])


class RateMealRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


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


@router.post("/{meal_id}/rate")
async def rate_meal(meal_id: int, body: RateMealRequest, manager: MCPManagerDep) -> dict[str, Any]:
    result = await manager.call_tool(
        "user_intelligence", "rate_meal", {"meal_id": meal_id, "rating": body.rating}
    )
    meal = unwrap_mcp_result(result)

    profile_result = await manager.call_tool("user_intelligence", "get_user_profile", {})
    profile = unwrap_mcp_result(profile_result)

    return {
        "meal": meal,
        "cuisine_preferences": profile.get("cuisine_preferences"),
        "protein_preference": profile.get("protein_preference"),
    }
