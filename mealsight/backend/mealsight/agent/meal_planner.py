"""generate_meal_plan — the single entry point for multi-day meal
planning, mirroring mealsight.agent.runner.run_recommendation's own
shape exactly: bind a trace id, start (or reuse) an MCPClientManager,
run to completion, return a result. Not a LangGraph node and not part
of the eleven-node recommendation pipeline — planning is a genuinely
different operation (no photo/voice/text perception, no single
LLM-judged choice among a short list) that happens to need the same
three MCP servers, so it gets its own orchestrator rather than being
bolted onto graph.py's own sequential shape.

THIS is the one place in the whole feature allowed to reach across
recipe_engine, pantry_manager, and user_intelligence — see
mealsight.planning's own package docstring for the boundary this
enforces: build_schedule (the actual scheduling algorithm) never
touches a database or an MCP client at all, only plain data this module
hands it after gathering it via the exact same tools every other agent
node already calls through MCPClientManager.call_tool.

NO NEW MCP TOOLS: every piece of data this module needs already exists
as one of the 24 tools across the three servers (search_recipes,
match_ingredients, get_recipe, scale_recipe, calculate_nutrition;
get_pantry, flag_expiring, create_grocery_list; check_repetition,
get_user_profile) — confirmed by reading every existing tool's
docstring before writing a line of this module, not assumed. That
absence of any new server-side tool is itself the evidence the
architecture constraint (cross-server composition is the agent's job,
never a single tool's) is actually satisfiable this way.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

from mealsight.agent.mcp_client import MCPClientManager
from mealsight.config.settings import settings
from mealsight.matching.normalize import normalize_ingredient
from mealsight.planning import PlanCandidate, PlanConstraintsUnsatisfiable, build_schedule
from mealsight.seed.recipe_parsing import PROTEIN_TERMS
from mealsight.utils.logging import bind_trace_id, get_logger

logger = get_logger("mealsight.agent.meal_planner")

# How many recipe_engine search results become the planning candidate
# pool — generous enough that `days` picks (default 5, realistically up
# to a week or two) still have real variety to choose from without
# calling match_ingredients (one real MCP round-trip each) against the
# entire corpus. Same bounding-the-expensive-tier discipline agent/
# nodes/match_rank.py already uses for its own TOP_N_CANDIDATES_TO_MATCH.
MAX_PLANNING_CANDIDATES = 40

# Of the candidate pool, how many (by preliminary match_score) get
# check_repetition called against them — mirrors match_rank.py's own
# CHECK_REPETITION_TOP_K discipline, for the identical reason: it hits
# user_intelligence's own history store per call, so it's bounded
# separately from the (cheaper, local) match_ingredients tier.
REPETITION_CHECK_TOP_K = 20

NEUTRAL_CUISINE_SCORE = 0.5


def _protein_type(ingredient_names: list[str]) -> str | None:
    """Derives a recipe's own defining protein, the same way seed.
    recipe_parsing.assign_importances derives a CRITICAL ingredient:
    the first ingredient (in the order match_ingredients itself
    returned them) whose normalized name is a whole-word match against
    PROTEIN_TERMS. None for a recipe with no protein-forward ingredient
    at all (a vegetable/grain-forward dish) — never guessed.

    Deliberately reimplements just the whole-word check inline rather
    than importing seed.recipe_parsing's own private _matches_any_term_
    whole_word: that function is private to a module meant for one-time
    seeding scripts, and the check itself is three lines against a
    public, already-imported constant (PROTEIN_TERMS) — not worth
    crossing that module's own privacy boundary for.
    """
    for name in ingredient_names:
        normalized = normalize_ingredient(name)
        if any(re.search(rf"\b{re.escape(term)}(?:es|s)?\b", normalized) for term in PROTEIN_TERMS):
            # The matched TERM, not the ingredient's own full name, is
            # what "protein_type" means here — "chicken thighs" and
            # "chicken breast" both count as the same "chicken" for the
            # max_same_protein_per_week cap to mean anything.
            return next(
                term
                for term in PROTEIN_TERMS
                if re.search(rf"\b{re.escape(term)}(?:es|s)?\b", normalized)
            )
    return None


def _all_ingredient_names(match_data: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("matched_items", "missing_items", "partial_matches"):
        for item in match_data.get(key) or []:
            name = item.get("name") if isinstance(item, dict) else None
            if isinstance(name, str):
                names.append(name)
    return names


async def _gather_context(manager: MCPClientManager) -> tuple[list[str], set[str], dict[str, float]]:
    pantry_result, expiring_result, profile_result = await asyncio.gather(
        manager.call_tool("pantry_manager", "get_pantry", {}),
        manager.call_tool("pantry_manager", "flag_expiring", {}),
        manager.call_tool("user_intelligence", "get_user_profile", {}),
    )

    pantry_names: list[str] = []
    if pantry_result.success and isinstance(pantry_result.data, dict):
        pantry_names = [
            str(item["name"]) for item in pantry_result.data.get("items", []) if item.get("name")
        ]

    expiring_names: set[str] = set()
    if expiring_result.success and isinstance(expiring_result.data, dict):
        expiring_names = {
            normalize_ingredient(item["name"])
            for item in expiring_result.data.get("items", [])
            if item.get("name")
        }

    cuisine_preferences: dict[str, float] = {}
    if profile_result.success and isinstance(profile_result.data, dict):
        raw = profile_result.data.get("cuisine_preferences") or {}
        cuisine_preferences = {
            str(k).lower(): float(v) for k, v in raw.items() if isinstance(v, (int, float))
        }

    return pantry_names, expiring_names, cuisine_preferences


async def _build_candidates(
    manager: MCPClientManager,
    dietary_restrictions: list[str],
    max_cook_time_minutes: int | None,
    avoid_ingredients: list[str],
    pantry_names: list[str],
    expiring_names: set[str],
    cuisine_preferences: dict[str, float],
) -> list[PlanCandidate]:
    # cuisine is deliberately NOT passed as a hard filter here — see
    # this module's own report to the user: hard-filtering to one
    # cuisine would make "avoid the same cuisine on consecutive days"
    # impossible to satisfy at all. Cuisine still shapes the plan, via
    # cuisine_score below, exactly the way agent/nodes/match_rank.py
    # already uses a learned cuisine preference as a scoring signal
    # rather than a filter.
    search_result = await manager.call_tool(
        "recipe_engine",
        "search_recipes",
        {
            "dietary_filters": dietary_restrictions,
            "max_cook_time": max_cook_time_minutes,
            "cuisine": None,
            "meal_type": None,
            "max_results": MAX_PLANNING_CANDIDATES,
            "pantry_ingredients": pantry_names,
        },
    )
    if not (search_result.success and isinstance(search_result.data, dict)):
        raise PlanConstraintsUnsatisfiable(0, "recipe search itself failed — no candidates to plan from.")
    results = search_result.data.get("results", [])
    if not results:
        raise PlanConstraintsUnsatisfiable(
            0,
            "no recipes matched the given dietary restrictions and cook-time limit at all — "
            "there is nothing honest to plan with.",
        )

    avoid_normalized = {normalize_ingredient(name) for name in avoid_ingredients}

    candidates: list[PlanCandidate] = []
    for recipe in results:
        recipe_id = recipe.get("recipe_id") or recipe.get("id")
        if not recipe_id:
            continue
        match_result = await manager.call_tool(
            "recipe_engine",
            "match_ingredients",
            {
                "recipe_id": recipe_id,
                "available_ingredients": pantry_names,
                "dietary_restrictions": dietary_restrictions,
            },
        )
        if not (match_result.success and isinstance(match_result.data, dict)):
            continue
        match_data = match_result.data
        all_names = _all_ingredient_names(match_data)

        if avoid_normalized and any(normalize_ingredient(n) in avoid_normalized for n in all_names):
            continue

        cuisine = recipe.get("cuisine")
        cuisine_score = (
            cuisine_preferences.get(cuisine.lower(), NEUTRAL_CUISINE_SCORE)
            if cuisine
            else NEUTRAL_CUISINE_SCORE
        )
        uses_expiring = [n for n in all_names if normalize_ingredient(n) in expiring_names]
        missing_names = [
            item.get("name")
            for item in match_data.get("missing_items") or []
            if isinstance(item, dict) and item.get("name")
        ]

        candidates.append(
            PlanCandidate(
                recipe_id=recipe_id,
                name=recipe.get("name", recipe_id),
                cuisine=cuisine,
                meal_type=recipe.get("meal_type"),
                cook_time_minutes=recipe.get("cook_time_minutes"),
                match_score=float(match_data.get("match_score", 0.0)),
                can_cook=bool(match_data.get("can_cook", False)),
                critical_missing=list(match_data.get("critical_missing") or []),
                missing_ingredient_names=[str(n) for n in missing_names],
                all_ingredient_names=all_names,
                protein_type=_protein_type(all_names),
                uses_expiring_ingredient_names=uses_expiring,
                cuisine_score=cuisine_score,
                repetition_score=0.0,
                repetition_recommendation=None,
            )
        )

    if not candidates:
        raise PlanConstraintsUnsatisfiable(
            0, "avoid_ingredients excluded every candidate the search itself found."
        )

    candidates.sort(key=lambda c: c.match_score, reverse=True)
    tier = candidates[:REPETITION_CHECK_TOP_K]
    enriched: dict[str, PlanCandidate] = {c.recipe_id: c for c in candidates}
    for candidate in tier:
        rep_result = await manager.call_tool(
            "user_intelligence", "check_repetition", {"recipe_id": candidate.recipe_id}
        )
        if rep_result.success and isinstance(rep_result.data, dict):
            enriched[candidate.recipe_id] = candidate.model_copy(
                update={
                    "repetition_score": float(rep_result.data.get("repetition_score", 0.0)),
                    "repetition_recommendation": rep_result.data.get("recommendation"),
                }
            )

    return list(enriched.values())


async def _enrich_day(
    manager: MCPClientManager, day: Any, servings: int
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Returns (missing_by_recipe entry for create_grocery_list,
    nutrition data or None). Scales each missing ingredient's own
    quantity from the recipe's real base servings to the plan's target
    servings — a plain float scale, not scaled display-string
    round-tripping (scale_recipe's own quantity_display is formatted
    for a human to read, not for create_grocery_list's numeric field)."""
    recipe_result = await manager.call_tool("recipe_engine", "get_recipe", {"recipe_id": day.recipe_id})
    missing_ingredients: list[dict[str, Any]] = []
    if recipe_result.success and isinstance(recipe_result.data, dict):
        servings_base = recipe_result.data.get("servings_base") or 1
        scale = servings / servings_base if servings_base else 1.0
        by_name = {
            normalize_ingredient(ing["name"]): ing
            for ing in recipe_result.data.get("ingredients", [])
            if isinstance(ing, dict) and ing.get("name")
        }
        for name in day.missing_ingredient_names:
            source = by_name.get(normalize_ingredient(name))
            quantity = source.get("quantity") if source else None
            unit = source.get("unit") if source else None
            # get_recipe's own ingredient importance when the name
            # resolves back to it; "important" as a safe, non-critical
            # default otherwise (a name match_ingredients reported that
            # this lookup couldn't re-find is rare enough — a genuine
            # naming mismatch — that guessing "critical" would overstate
            # the gap more often than "important" would understate it).
            importance = source.get("importance") if source else "important"
            missing_ingredients.append(
                {
                    "name": name,
                    "quantity": quantity * scale if quantity is not None else None,
                    "unit": unit,
                    "importance": importance,
                }
            )

    nutrition_result = await manager.call_tool(
        "recipe_engine", "calculate_nutrition", {"recipe_id": day.recipe_id, "servings": servings}
    )
    nutrition_data = (
        nutrition_result.data
        if nutrition_result.success and isinstance(nutrition_result.data, dict)
        else None
    )

    grocery_entry = {
        "recipe_id": day.recipe_id,
        "recipe_name": day.name,
        "missing_ingredients": missing_ingredients,
    }
    return grocery_entry, nutrition_data


def _nutrition_summary(nutrition_by_day: list[dict[str, Any] | None]) -> dict[str, Any]:
    fields = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg")
    totals = dict.fromkeys(fields, 0.0)
    covered = [n for n in nutrition_by_day if n is not None]
    for entry in covered:
        for field in fields:
            value = entry.get(field)
            if isinstance(value, (int, float)):
                totals[field] += float(value)

    days_total = len(nutrition_by_day)
    days_covered = len(covered)
    coverage_note = (
        f"calculated from {days_covered} of {days_total} day(s) — the rest had no nutrition "
        "data available"
        if days_covered < days_total
        else f"calculated from all {days_total} day(s)"
    )
    return {
        "total_calories": totals["calories"],
        "total_protein_g": totals["protein_g"],
        "total_carbs_g": totals["carbs_g"],
        "total_fat_g": totals["fat_g"],
        "total_fiber_g": totals["fiber_g"],
        "total_sodium_mg": totals["sodium_mg"],
        "days_with_nutrition": days_covered,
        "days_total": days_total,
        "coverage_note": coverage_note,
    }


async def generate_meal_plan(
    days: int = 5,
    servings: int = 2,
    dietary_restrictions: list[str] | None = None,
    max_cook_time_minutes: int | None = None,
    avoid_ingredients: list[str] | None = None,
    *,
    use_overlap_optimization: bool = True,
    manager: MCPClientManager | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Runs one full multi-day meal plan end to end. Mirrors run_
    recommendation's own manager-reuse contract exactly: pass an
    already-started MCPClientManager (mealsight.api holds one for the
    process lifetime) to reuse its live subprocesses, or omit it to
    start and tear down a fresh one for just this call.

    use_overlap_optimization exists to MEASURE the cross-day overlap
    term's real effect (see this project's own verification run,
    section 3) — always True for a real user-facing plan; setting it
    False is a diagnostic, not a feature.

    Raises PlanConstraintsUnsatisfiable — never returns a plan shorter
    than `days` — when the given constraints genuinely cannot be
    filled honestly (see build_schedule's own docstring for exactly
    when this fires) or ValueError for a non-positive days/servings.
    """
    if days <= 0:
        raise ValueError(f"days must be a positive integer, got {days}.")
    if servings <= 0:
        raise ValueError(f"servings must be a positive integer, got {servings}.")

    trace_id = trace_id or str(uuid.uuid4())
    bind_trace_id(trace_id)
    started_at = time.monotonic()
    logger.info("meal_plan_started", trace_id=trace_id, days=days, servings=servings)

    dietary_restrictions = dietary_restrictions or []
    avoid_ingredients = avoid_ingredients or []

    async def _run(active_manager: MCPClientManager) -> dict[str, Any]:
        pantry_names, expiring_names, cuisine_preferences = await _gather_context(active_manager)
        candidates = await _build_candidates(
            active_manager,
            dietary_restrictions,
            max_cook_time_minutes,
            avoid_ingredients,
            pantry_names,
            expiring_names,
            cuisine_preferences,
        )
        schedule = build_schedule(
            candidates,
            days,
            settings.max_same_protein_per_week,
            enable_overlap_bonus=use_overlap_optimization,
        )

        missing_by_recipe = []
        nutrition_by_day = []
        plan_days: list[dict[str, Any]] = []
        for day in schedule.days:
            grocery_entry, nutrition_data = await _enrich_day(active_manager, day, servings)
            missing_by_recipe.append(grocery_entry)
            nutrition_by_day.append(nutrition_data)
            plan_days.append(
                {
                    "day_index": day.day_index,
                    "recipe_id": day.recipe_id,
                    "recipe_name": day.name,
                    "cuisine": day.cuisine,
                    "protein_type": day.protein_type,
                    "servings": servings,
                    "match_score": day.match_score,
                    "can_cook": day.can_cook,
                    "uses_expiring_ingredient_names": day.uses_expiring_ingredient_names,
                    "missing_ingredient_names": day.missing_ingredient_names,
                    "shared_missing_ingredient_names": day.shared_missing_ingredient_names,
                    "cuisine_repeat_forced": day.cuisine_repeat_forced,
                }
            )

        grocery_result = await active_manager.call_tool(
            "pantry_manager", "create_grocery_list", {"missing_by_recipe": missing_by_recipe}
        )
        grocery_list = (
            grocery_result.data
            if grocery_result.success and isinstance(grocery_result.data, dict)
            else None
        )

        all_missing = set()
        shared_missing = set()
        for day_data in plan_days:
            all_missing.update(day_data["missing_ingredient_names"])
            shared_missing.update(day_data["shared_missing_ingredient_names"])

        return {
            "days": plan_days,
            "grocery_list": grocery_list,
            "total_distinct_ingredients": len(all_missing),
            "shared_ingredient_count": len(shared_missing),
            "nutrition_summary": _nutrition_summary(nutrition_by_day),
            "wall_clock_seconds": round(time.monotonic() - started_at, 2),
            "trace_id": trace_id,
        }

    if manager is not None:
        result = await _run(manager)
    else:
        async with MCPClientManager() as owned_manager:
            result = await _run(owned_manager)

    logger.info(
        "meal_plan_finished",
        trace_id=trace_id,
        wall_clock_seconds=result["wall_clock_seconds"],
        total_distinct_ingredients=result["total_distinct_ingredients"],
        shared_ingredient_count=result["shared_ingredient_count"],
    )
    return result
