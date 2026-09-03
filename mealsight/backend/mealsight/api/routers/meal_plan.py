"""POST /api/meal-plan — runs mealsight.agent.meal_planner.
generate_meal_plan directly, the same shape POST /api/recommend uses
for run_recommendation: this is a real agent-layer orchestration call,
not an MCP tool proxy (there is no meal-planning MCP tool at all — see
meal_planner.py's own module docstring for why), so this router talks
to the orchestrator function directly rather than through
mcp_proxy.unwrap_mcp_result.

Reuses the app's own long-lived MCPClientManager (app.state.mcp_manager)
rather than starting a fresh one per request — the same subprocess-
startup-cost avoidance every other router in this package already
relies on.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from mealsight.agent.meal_planner import generate_meal_plan
from mealsight.api.dependencies import MCPManagerDep
from mealsight.api.errors import APIError
from mealsight.planning import PlanConstraintsUnsatisfiable

router = APIRouter(prefix="/api/meal-plan", tags=["meal-plan"])


class MealPlanRequest(BaseModel):
    days: int = 5
    servings: int = 2
    dietary_restrictions: list[str] | None = None
    max_cook_time_minutes: int | None = None
    avoid_ingredients: list[str] | None = None


@router.post("")
async def create_meal_plan(body: MealPlanRequest, manager: MCPManagerDep) -> dict[str, Any]:
    try:
        return await generate_meal_plan(
            days=body.days,
            servings=body.servings,
            dietary_restrictions=body.dietary_restrictions,
            max_cook_time_minutes=body.max_cook_time_minutes,
            avoid_ingredients=body.avoid_ingredients,
            manager=manager,
        )
    except ValueError as exc:
        raise APIError(400, "validation_error", str(exc)) from exc
    except PlanConstraintsUnsatisfiable as exc:
        raise APIError(422, "plan_unsatisfiable", str(exc)) from exc
