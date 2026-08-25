"""GET/PATCH /api/profile — thin proxies onto user_intelligence's own
get_user_profile/update_preferences tools through the shared
MCPClientManager.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/profile", tags=["profile"])


class PreferenceUpdateRequest(BaseModel):
    preference_type: str
    value: Any


@router.get("")
async def get_profile(manager: MCPManagerDep) -> dict[str, Any]:
    result = await manager.call_tool("user_intelligence", "get_user_profile", {})
    return unwrap_mcp_result(result)


@router.patch("")
async def update_profile(body: PreferenceUpdateRequest, manager: MCPManagerDep) -> dict[str, Any]:
    arguments = {"preference_type": body.preference_type, "value": body.value}
    result = await manager.call_tool("user_intelligence", "update_preferences", arguments)
    return unwrap_mcp_result(result)
