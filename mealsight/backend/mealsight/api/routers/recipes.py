"""GET /api/recipes/{id}, GET /api/recipes/search, and GET /api/recipes/
by-ingredients — thin proxies onto recipe_engine's own get_recipe/
search_recipes/get_recipe_by_ingredients tools through the shared
MCPClientManager.

by-ingredients is registered BEFORE the {recipe_id} catch-all route,
same as search already is — FastAPI matches routes in declaration
order, so a specific path has to come before a path parameter that
would otherwise swallow it (a request for /api/recipes/by-ingredients
would otherwise resolve recipe_id="by-ingredients").
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

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


@router.get("/by-ingredients")
async def get_recipe_by_ingredients(
    manager: MCPManagerDep,
    # A REQUIRED list[str] with no default is otherwise ambiguous to
    # FastAPI (it defaults an unannotated required list-typed parameter
    # to a REQUEST BODY field, not a query param, since a query param
    # is normally expected to have a default) — Query(...) forces the
    # query-param interpretation this GET endpoint actually needs.
    ingredients: Annotated[list[str], Query()],
    minimum_match_percentage: float = 0.6,
) -> dict[str, Any]:
    arguments = {"ingredients": ingredients, "minimum_match_percentage": minimum_match_percentage}
    result = await manager.call_tool("recipe_engine", "get_recipe_by_ingredients", arguments)
    return unwrap_mcp_result(result)


@router.get("/{recipe_id}")
async def get_recipe(recipe_id: str, manager: MCPManagerDep) -> dict[str, Any]:
    result = await manager.call_tool("recipe_engine", "get_recipe", {"recipe_id": recipe_id})
    return unwrap_mcp_result(result)
