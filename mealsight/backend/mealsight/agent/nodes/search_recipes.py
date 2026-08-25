"""search_recipes — calls recipe_engine's own search_recipes tool with
unified_request's hard constraints: dietary_restrictions, max_cook_time_
minutes, cuisine_preference, plus meal_type from get_context's own
context_signals when available. Dietary restrictions are inviolable and
are never touched by anything below.

If the first search comes back empty, this node retries with a
progressively (cumulatively) relaxed set of filters, streaming plain-
language messages so the user sees exactly what changed and why:

    1. drop cuisine
    2. raise the cook-time ceiling (see COOK_TIME_RELAXATION_FACTOR)
    3. drop meal_type

Each step is skipped (no wasted duplicate call) if the corresponding
filter was never set to begin with. If every applicable step still
yields nothing, recipe_candidates is left empty and search_exhausted is
set True so reason (node 8) can explain the situation instead of
fabricating a recommendation.

total_matched is stored alongside recipe_candidates: recipe_engine's own
count of everything that matched, which can exceed len(recipe_
candidates) once max_results caps the returned list — reason uses it to
say how many were actually considered.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.state import MealSightState
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.search_recipes")

NODE_NAME = "search_recipes"

MAX_SEARCH_RESULTS = 20

# How much the cook-time ceiling is raised during relaxation. A 50%
# increase is generous enough to plausibly surface something new
# without abandoning the user's stated time pressure entirely.
COOK_TIME_RELAXATION_FACTOR = 1.5


async def _search(
    runtime: Runtime[AgentContext],
    dietary_filters: list[str],
    max_cook_time: int | None,
    cuisine: str | None,
    meal_type: str | None,
) -> tuple[list[dict[str, Any]], int]:
    result = await runtime.context.mcp.call_tool(
        "recipe_engine",
        "search_recipes",
        {
            "dietary_filters": dietary_filters,
            "max_cook_time": max_cook_time,
            "cuisine": cuisine,
            "meal_type": meal_type,
            "max_results": MAX_SEARCH_RESULTS,
        },
    )
    if not (result.success and isinstance(result.data, dict)):
        logger.warning("search_recipes_call_failed", error=result.error)
        return [], 0
    results = result.data.get("results", [])
    total_matched = result.data.get("total_matched", 0)
    if not isinstance(results, list):
        results = []
    if not isinstance(total_matched, int):
        total_matched = len(results)
    return results, total_matched


async def search_recipes(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input."]}

    unified = state.get("unified_request")
    if unified is None:
        logger.warning("node_finished", node=NODE_NAME, reason="no unified request")
        return {
            "recipe_candidates": [],
            "total_matched": 0,
            "search_exhausted": True,
            "stream_messages": [f"[{NODE_NAME}] No combined request to search recipes for."],
        }

    dietary_filters = unified.dietary_restrictions
    cuisine = unified.cuisine_preference
    max_cook_time = unified.max_cook_time_minutes
    context_signals = state.get("context_signals") or {}
    meal_type = context_signals.get("meal_type")

    messages: list[str] = []

    try:
        results, total_matched = await _search(runtime, dietary_filters, max_cook_time, cuisine, meal_type)

        if not results:
            messages.append(
                f"[{NODE_NAME}] No recipes matched your exact request — trying with fewer constraints "
                "(dietary restrictions always stay in place)."
            )

            if cuisine is not None:
                messages.append(f"[{NODE_NAME}] Dropping the {cuisine} cuisine preference and trying again.")
                cuisine = None
                results, total_matched = await _search(
                    runtime, dietary_filters, max_cook_time, cuisine, meal_type
                )

        if not results and max_cook_time is not None:
            raised = max(max_cook_time + 1, round(max_cook_time * COOK_TIME_RELAXATION_FACTOR))
            messages.append(
                f"[{NODE_NAME}] Still nothing — raising the cook-time limit from {max_cook_time} to "
                f"{raised} minutes and trying again."
            )
            max_cook_time = raised
            results, total_matched = await _search(
                runtime, dietary_filters, max_cook_time, cuisine, meal_type
            )

        if not results and meal_type is not None:
            messages.append(
                f"[{NODE_NAME}] Still nothing — dropping the {meal_type} meal-type filter and trying again."
            )
            meal_type = None
            results, total_matched = await _search(
                runtime, dietary_filters, max_cook_time, cuisine, meal_type
            )

        if results:
            relaxed = len(messages) > 0
            suffix = " after relaxing the search" if relaxed else ""
            messages.append(f"[{NODE_NAME}] Found {total_matched} matching recipe(s){suffix}.")
            logger.info("node_finished", node=NODE_NAME, total_matched=total_matched, relaxed=relaxed)
            return {
                "recipe_candidates": results,
                "total_matched": total_matched,
                "search_exhausted": False,
                "stream_messages": messages,
            }

        kept = ", ".join(dietary_filters) if dietary_filters else "(none)"
        messages.append(
            f"[{NODE_NAME}] No recipes matched even after relaxing everything possible "
            f"(dietary restrictions kept throughout: {kept})."
        )
        logger.warning("node_finished", node=NODE_NAME, total_matched=0, search_exhausted=True)
        return {
            "recipe_candidates": [],
            "total_matched": 0,
            "search_exhausted": True,
            "stream_messages": messages,
        }
    except Exception:
        logger.error("search_recipes_unexpected_failure", exc_info=True)
        messages.append(f"[{NODE_NAME}] Recipe search failed unexpectedly.")
        return {
            "recipe_candidates": [],
            "total_matched": 0,
            "search_exhausted": True,
            "stream_messages": messages,
        }
