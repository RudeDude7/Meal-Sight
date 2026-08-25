"""GET /api/recipes/{id} and GET /api/recipes/search — thin proxies onto
recipe_engine's own get_recipe/search_recipes tools through the shared
MCPClientManager.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.mcp_proxy import unwrap_mcp_result

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


@router.get("/search")
async def search_recipes(
    manager: MCPManagerDep,
    dietary_filters: list[str] | None = None,
    max_cook_time: int | None = None,
    cuisine: str | None = None,
    meal_type: str | None = None,
    max_results: int = 20,
) -> dict[str, Any]:
    arguments = {
        "dietary_filters": dietary_filters,
        "max_cook_time": max_cook_time,
        "cuisine": cuisine,
        "meal_type": meal_type,
        "max_results": max_results,
    }
    result = await manager.call_tool("recipe_engine", "search_recipes", arguments)
    return unwrap_mcp_result(result)


@router.get("/{recipe_id}")
async def get_recipe(recipe_id: str, manager: MCPManagerDep) -> dict[str, Any]:
    result = await manager.call_tool("recipe_engine", "get_recipe", {"recipe_id": recipe_id})
    return unwrap_mcp_result(result)
