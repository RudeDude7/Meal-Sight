"""Tests for mealsight.agent.meal_planner.generate_meal_plan — the
orchestration layer, mocked at the MCPClientManager boundary (a
FakeManager, mirroring test_nodes.py's own FakeMCP but supporting a
per-call callable response since this module calls match_ingredients/
get_recipe/calculate_nutrition/check_repetition once PER recipe_id,
not once per (server, tool) pair)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from mealsight.agent.mcp_client import ToolCallResult
from mealsight.agent.meal_planner import generate_meal_plan
from mealsight.planning import PlanConstraintsUnsatisfiable

Responder = ToolCallResult | Callable[[dict[str, Any]], ToolCallResult]


class FakeManager:
    def __init__(self, responses: dict[tuple[str, str], Responder]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_tool(
        self, server: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        arguments = arguments or {}
        self.calls.append((server, tool_name, arguments))
        responder = self._responses.get((server, tool_name))
        if responder is None:
            return ToolCallResult(success=False, error="unconfigured")
        if callable(responder):
            return responder(arguments)
        return responder


def _recipe(recipe_id: str, cuisine: str, name: str | None = None) -> dict[str, Any]:
    return {
        "id": recipe_id,
        "name": name or recipe_id,
        "cuisine": cuisine,
        "meal_type": "main",
        "cook_time_minutes": 30,
        "dietary_tags": [],
    }


def _match_result(recipe_id: str, missing: list[str], match_score: float = 0.8) -> ToolCallResult:
    return ToolCallResult(
        success=True,
        data={
            "match_score": match_score,
            "can_cook": not missing,
            "matched_items": [],
            "substitutable_items": [],
            "partial_matches": [],
            "missing_items": [{"name": name, "importance": "important"} for name in missing],
            "critical_missing": [],
            "summary": "",
        },
    )


def _standard_manager(recipe_ids: list[tuple[str, str]], *, missing: dict[str, list[str]]) -> FakeManager:
    """recipe_ids: [(id, cuisine), ...]. missing: {id: [ingredient names]}."""

    def search(_args: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(
            success=True,
            data={
                "results": [_recipe(rid, cuisine) for rid, cuisine in recipe_ids],
                "total_matched": len(recipe_ids),
            },
        )

    def match(args: dict[str, Any]) -> ToolCallResult:
        recipe_id = args["recipe_id"]
        return _match_result(recipe_id, missing.get(recipe_id, []))

    def get_recipe(args: dict[str, Any]) -> ToolCallResult:
        recipe_id = args["recipe_id"]
        return ToolCallResult(
            success=True,
            data={
                "id": recipe_id,
                "name": recipe_id,
                "servings_base": 2,
                "ingredients": [
                    {"name": name, "quantity": 1.0, "unit": "count", "importance": "important"}
                    for name in missing.get(recipe_id, [])
                ],
            },
        )

    def nutrition(_args: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(success=True, data={"calories": 400.0, "protein_g": 20.0})

    return FakeManager(
        {
            ("pantry_manager", "get_pantry"): ToolCallResult(success=True, data={"items": [], "count": 0}),
            ("pantry_manager", "flag_expiring"): ToolCallResult(
                success=True, data={"items": [], "count": 0}
            ),
            ("user_intelligence", "get_user_profile"): ToolCallResult(
                success=True, data={"cuisine_preferences": {}}
            ),
            ("recipe_engine", "search_recipes"): search,
            ("recipe_engine", "match_ingredients"): match,
            ("recipe_engine", "get_recipe"): get_recipe,
            ("recipe_engine", "calculate_nutrition"): nutrition,
            ("user_intelligence", "check_repetition"): ToolCallResult(
                success=True, data={"repetition_score": 0.0, "recommendation": "acceptable"}
            ),
            ("pantry_manager", "create_grocery_list"): ToolCallResult(
                success=True, data={"id": 1, "status": "active", "sections": []}
            ),
        }
    )


async def test_generates_a_plan_for_the_requested_number_of_days() -> None:
    recipe_ids = [(f"r{i}", f"cuisine{i}") for i in range(5)]
    manager = _standard_manager(recipe_ids, missing={})

    result = await generate_meal_plan(days=5, servings=2, manager=manager)  # type: ignore[arg-type]

    assert len(result["days"]) == 5
    assert result["days"][0]["servings"] == 2


async def test_dietary_restrictions_are_passed_through_to_search_recipes() -> None:
    recipe_ids = [(f"r{i}", f"cuisine{i}") for i in range(3)]
    manager = _standard_manager(recipe_ids, missing={})

    await generate_meal_plan(
        days=3, servings=2, dietary_restrictions=["vegan"], manager=manager  # type: ignore[arg-type]
    )

    search_call = next(args for server, tool, args in manager.calls if tool == "search_recipes")
    assert search_call["dietary_filters"] == ["vegan"]


async def test_cuisine_is_never_passed_as_a_hard_filter_to_search_recipes() -> None:
    # Confirms the architecture decision directly: cuisine variety would
    # be impossible if search_recipes hard-filtered to one cuisine.
    recipe_ids = [(f"r{i}", f"cuisine{i}") for i in range(3)]
    manager = _standard_manager(recipe_ids, missing={})

    await generate_meal_plan(days=3, servings=2, manager=manager)  # type: ignore[arg-type]

    search_call = next(args for server, tool, args in manager.calls if tool == "search_recipes")
    assert search_call["cuisine"] is None


async def test_avoid_ingredients_excludes_matching_candidates() -> None:
    recipe_ids = [("has-peanuts", "thai"), ("clean", "italian"), ("also-clean", "mexican")]
    manager = _standard_manager(recipe_ids, missing={"has-peanuts": ["peanuts"]})

    result = await generate_meal_plan(
        days=2, servings=2, avoid_ingredients=["peanuts"], manager=manager  # type: ignore[arg-type]
    )

    chosen_ids = {day["recipe_id"] for day in result["days"]}
    assert "has-peanuts" not in chosen_ids


async def test_grocery_list_is_built_via_create_grocery_list_not_reimplemented() -> None:
    recipe_ids = [("r0", "italian"), ("r1", "mexican")]
    manager = _standard_manager(recipe_ids, missing={"r0": ["saffron"], "r1": ["saffron", "cumin"]})

    result = await generate_meal_plan(days=2, servings=2, manager=manager)  # type: ignore[arg-type]

    assert result["grocery_list"] is not None
    grocery_call = next(args for server, tool, args in manager.calls if tool == "create_grocery_list")
    recipe_ids_in_call = {entry["recipe_id"] for entry in grocery_call["missing_by_recipe"]}
    assert recipe_ids_in_call == {"r0", "r1"}


async def test_impossible_constraints_propagate_as_plan_constraints_unsatisfiable() -> None:
    # Only 2 candidates, 5 days requested — genuinely unfillable.
    recipe_ids = [("r0", "italian"), ("r1", "mexican")]
    manager = _standard_manager(recipe_ids, missing={})

    with pytest.raises(PlanConstraintsUnsatisfiable):
        await generate_meal_plan(days=5, servings=2, manager=manager)  # type: ignore[arg-type]


async def test_no_candidates_at_all_raises_honestly() -> None:
    manager = FakeManager(
        {
            ("pantry_manager", "get_pantry"): ToolCallResult(success=True, data={"items": [], "count": 0}),
            ("pantry_manager", "flag_expiring"): ToolCallResult(
                success=True, data={"items": [], "count": 0}
            ),
            ("user_intelligence", "get_user_profile"): ToolCallResult(
                success=True, data={"cuisine_preferences": {}}
            ),
            ("recipe_engine", "search_recipes"): ToolCallResult(
                success=True, data={"results": [], "total_matched": 0}
            ),
        }
    )

    with pytest.raises(PlanConstraintsUnsatisfiable):
        await generate_meal_plan(days=5, servings=2, manager=manager)  # type: ignore[arg-type]


async def test_zero_or_negative_days_raises_value_error() -> None:
    manager = _standard_manager([], missing={})
    with pytest.raises(ValueError):
        await generate_meal_plan(days=0, servings=2, manager=manager)  # type: ignore[arg-type]


async def test_wall_clock_seconds_is_reported() -> None:
    recipe_ids = [(f"r{i}", f"cuisine{i}") for i in range(3)]
    manager = _standard_manager(recipe_ids, missing={})

    result = await generate_meal_plan(days=3, servings=2, manager=manager)  # type: ignore[arg-type]

    assert result["wall_clock_seconds"] >= 0.0


async def test_total_distinct_and_shared_ingredient_counts_are_reported() -> None:
    recipe_ids = [("r0", "italian"), ("r1", "mexican")]
    manager = _standard_manager(recipe_ids, missing={"r0": ["saffron"], "r1": ["saffron"]})

    result = await generate_meal_plan(days=2, servings=2, manager=manager)  # type: ignore[arg-type]

    assert result["total_distinct_ingredients"] == 1
    assert result["shared_ingredient_count"] == 1
