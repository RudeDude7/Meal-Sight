"""GET/PATCH /api/pantry, DELETE /api/pantry/{item_id} — thin proxies
onto pantry_manager's own get_pantry/update_pantry/remove_items tools
through the shared MCPClientManager. No direct database access here;
every response is exactly what the MCP tool itself returned (translated
through mealsight.api.mcp_proxy for error shapes).

DELETE by item_id specifically needs two real calls, not one:
remove_items itself only ever addresses an item by NAME plus a
quantity to remove, never by row id — so this endpoint first calls
get_pantry to resolve the id to a name and its current quantity, then
calls remove_items with that full quantity to delete the row outright,
rather than the API layer inventing a remove-by-id tool that doesn't
exist on the MCP server.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.errors import APIError
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/pantry", tags=["pantry"])


class PantryItemPayload(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None
    category: str
    freshness_status: str = "fresh"


class PantryUpdateRequest(BaseModel):
    items: list[PantryItemPayload]


@router.get("")
async def get_pantry(
    manager: MCPManagerDep,
    category: str | None = None,
    freshness_filter: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    arguments = {"category": category, "freshness_filter": freshness_filter, "search": search}
    result = await manager.call_tool("pantry_manager", "get_pantry", arguments)
    return unwrap_mcp_result(result)


@router.patch("")
async def update_pantry(body: PantryUpdateRequest, manager: MCPManagerDep) -> dict[str, Any]:
    arguments = {"items": [item.model_dump() for item in body.items]}
    result = await manager.call_tool("pantry_manager", "update_pantry", arguments)
    return unwrap_mcp_result(result)


@router.delete("/{item_id}")
async def delete_pantry_item(item_id: int, manager: MCPManagerDep) -> dict[str, Any]:
    pantry_result = unwrap_mcp_result(await manager.call_tool("pantry_manager", "get_pantry", {}))
    items = pantry_result.get("items", [])
    match = next((item for item in items if item.get("id") == item_id), None)
    if match is None:
        raise APIError(404, "not_found", f"No pantry item found with id {item_id}.")

    result = await manager.call_tool(
        "pantry_manager",
        "remove_items",
        {"items": [{"name": match["name"], "quantity_used": match["quantity"]}]},
    )
    return unwrap_mcp_result(result)
