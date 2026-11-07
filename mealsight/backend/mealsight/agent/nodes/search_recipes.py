"""search_recipes — calls recipe_engine's own search_recipes tool with
unified_request's hard constraints: dietary_restrictions, max_cook_time_
minutes, cuisine_preference, plus meal_type from get_context's own
context_signals when available. Dietary restrictions are inviolable and
are never touched by anything below.

MEAL_TYPE VOCABULARY RECONCILIATION: mealsight.user_intelligence.context
infers meal_type as one of "breakfast", "lunch", "dinner", "snack" from
the clock alone — a vocabulary that has nothing to do with the recipe
corpus's own real meal_type values (TheMealDB's own category taxonomy:
"main", "dessert", "side", "breakfast", "appetizer" — verified directly
against the real seeded data, not assumed; see this project's own phase
8.6 notes for the exact counts). Passing the inferred value straight
through as an exact-match filter meant it silently matched nothing on
effectively every request, since "dinner" is never literally a stored
meal_type. MEAL_TYPE_TO_CORPUS_TYPES below is the reconciliation: each
inferred time-of-day maps to the SET of corpus values plausible for it,
not a single value — "dinner" accepts "main" and "side" but not
"dessert", for instance.

If the first search comes back empty, this node retries with a
progressively (cumulatively) relaxed set of filters, streaming plain-
language messages so the user sees exactly what changed and why:

    1. drop the inferred meal_type (the SYSTEM's own guess from the
       clock — the least-informed constraint in play)
    2. raise the cook-time ceiling (see COOK_TIME_RELAXATION_FACTOR)
    3. drop cuisine (a THING THE USER ACTUALLY ASKED FOR — relaxed only
       once every constraint the system itself introduced is already
       gone)

Dietary restrictions are inviolable and are never relaxed at any stage.

If every applicable step still yields nothing, recipe_candidates is left
empty and search_exhausted is set True so reason (node 8) can explain
the situation instead of fabricating a recommendation.

total_matched is stored alongside recipe_candidates: recipe_engine's own
count of everything that matched, which can exceed len(recipe_
candidates) once max_results caps the returned list — reason uses it to
say how many were actually considered.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.nodes.match_rank import _match_ingredients, _pantry_and_unverified_names
from mealsight.agent.reasoning_facts import _recipe_ingredient_names
from mealsight.agent.state import MealSightState
from mealsight.matching.avoid import dish_hits, ingredient_hits
from mealsight.matching.diet import split_restrictions, violated_ingredient_restrictions
from mealsight.pantry.expiring import usable_pantry_names
from mealsight.user_intelligence.models import MealType
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.search_recipes")

NODE_NAME = "search_recipes"

MAX_SEARCH_RESULTS = 20

# The inferred meal type is a preference, not a requirement: if filtering to
# it leaves fewer candidates than a full list, the corpus is too thin there
# for a hard filter to be useful (the corpus has 7 breakfast recipes), so
# every meal type is searched instead. Without this, an 8am request for
# "dinner" got 7 breakfast recipes, none cookable, and was told nothing
# could be made while a dozen cookable mains existed.
MIN_MEAL_TYPE_POOL = MAX_SEARCH_RESULTS

# How much the cook-time ceiling is raised during relaxation. A 50%
# increase is generous enough to plausibly surface something new
# without abandoning the user's stated time pressure entirely.
COOK_TIME_RELAXATION_FACTOR = 1.5

# The reconciliation described in this module's own docstring above.
# Every inferred MealType value must have a non-empty entry here, and
# every entry must actually be non-empty against the real corpus — both
# checked directly (see tests/test_agent/test_nodes.py's own
# test_meal_type_mapping_produces_non_empty_results_against_real_corpus)
# rather than assumed. BREAKFAST IS THE HARD CASE: the corpus has only 7
# recipes genuinely tagged "breakfast" (out of 250) and nothing like a
# "brunch" category to widen it with. Deliberately kept to JUST
# "breakfast" rather than also folding in "main" (168 recipes — two
# thirds of the whole corpus) purely to hit a bigger number: diluting it
# that far would make the breakfast/dinner distinction this whole
# reconciliation exists to create effectively meaningless again, just
# via a different mechanism than the original bug. 7 genuinely
# breakfast-appropriate recipes is a real, honest, non-empty answer;
# 168 mostly-dinner recipes relabeled as "breakfast-compatible" would
# not be.
MEAL_TYPE_TO_CORPUS_TYPES: dict[MealType, tuple[str, ...]] = {
    "breakfast": ("breakfast",),
    "lunch": ("main", "side", "appetizer"),
    "dinner": ("main", "side"),
    # Everything but breakfast, deliberately NOT just dessert/appetizer. The
    # clock calls 15:00-16:59 and 21:00-04:59 "snack" (10 hours a day), and
    # it cannot tell a snack from a late dinner; filtering hard to the 64
    # dessert/appetizer recipes (60 of them desserts, no savory snack food
    # exists in the corpus) meant a dinner request at 22:30 returned 18
    # desserts and 2 appetizers, measured against the live pantry.
    "snack": ("main", "side", "appetizer", "dessert"),
}


def _pantry_ingredient_names(state: MealSightState) -> list[str]:
    return usable_pantry_names(state.get("pantry_items") or [])


async def _search(
    runtime: Runtime[AgentContext],
    dietary_filters: list[str],
    max_cook_time: int | None,
    cuisine: str | None,
    meal_type: str | None,
    pantry_ingredients: list[str],
) -> tuple[list[dict[str, Any]], int]:
    # meal_type crosses an untyped boundary here (context_signals is a
    # plain dict[str, Any], read back off agent state) — .get() rather
    # than a hard index lookup so a value that somehow isn't one of the
    # four known MealType literals degrades to "no meal-type filter"
    # instead of a KeyError.
    mapped = MEAL_TYPE_TO_CORPUS_TYPES.get(meal_type) if meal_type is not None else None  # type: ignore[call-overload]
    corpus_meal_types = list(mapped) if mapped is not None else None
    result = await runtime.context.mcp.call_tool(
        "recipe_engine",
        "search_recipes",
        {
            "dietary_filters": dietary_filters,
            "max_cook_time": max_cook_time,
            "cuisine": cuisine,
            "meal_type": corpus_meal_types,
            "max_results": MAX_SEARCH_RESULTS,
            "pantry_ingredients": pantry_ingredients,
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


async def _any_viable(
    runtime: Runtime[AgentContext],
    state: MealSightState,
    results: list[dict[str, Any]],
    avoid_terms: list[str],
    avoid_dishes: list[str],
    ingredient_restrictions: list[str] | None = None,
    all_restrictions: list[str] | None = None,
) -> bool:
    """Whether at least one candidate could actually be cooked from what is
    on hand and breaks no avoid list. Relaxation has to key on this, not on
    the set merely being non-empty: a non-empty set of recipes nothing in the
    pantry can make is, to the user, the same as no answer."""
    names, _ = _pantry_and_unverified_names(state)
    answered = False
    for recipe in results:
        recipe_id = recipe.get("recipe_id") or recipe.get("id")
        if not recipe_id:
            continue
        match_data = await _match_ingredients(runtime, str(recipe_id), names, all_restrictions, avoid_terms)
        if not match_data:
            continue
        answered = True
        if not match_data.get("can_cook"):
            continue
        names = _recipe_ingredient_names(match_data)
        if (
            ingredient_hits(avoid_terms, names)
            or dish_hits(avoid_dishes, str(recipe.get("name") or ""))
            or violated_ingredient_restrictions(ingredient_restrictions or [], names)
        ):
            continue
        return True
    # If the matcher could not be reached for any candidate there is no
    # evidence of a problem, so do not relax on the strength of nothing.
    return not answered


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

    # unified.dietary_restrictions is normalized onto mealsight.perception.
    # dietary.DIETARY_RESTRICTION_VOCABULARY, which spells multi-word
    # entries with a hyphen ("gluten-free", "dairy-free", "nut-free") —
    # but recipes.dietary_tags (mealsight.seed.recipe_parsing.derive_
    # dietary_tags' own output) spells the exact same concepts with an
    # underscore ("gluten_free", "dairy_free", "nut_free"). Passed
    # straight through with no translation, search_recipes' own SQL-level
    # `required_tags.issubset(tags)` check never matched a single recipe
    # for any of those three restrictions — a real defect found while
    # building eval/dimension2 (backend/eval/README.md and this project's
    # own notes/phase_9_7 have the full story), confirmed directly
    # against the real corpus: dietary_filters=["gluten-free"] matched 0
    # of 250 recipes; dietary_filters=["gluten_free"] matched 117. Single-
    # word restrictions (vegan, vegetarian, keto, pescatarian, ...) have
    # no hyphen to mismatch and were never affected.
    # Only restrictions the corpus actually carries as tags are search filters. The rest used to be
    # sent as tags too and matched zero recipes (see mealsight.matching.diet); they are enforced
    # against ingredient lists in match_rank instead.
    split = split_restrictions(unified.dietary_restrictions)
    dietary_filters = split.tag_filters
    cuisine = unified.cuisine_preference
    # Only a limit the user stated is a filter. The profile default ranks (see match_rank).
    max_cook_time = unified.stated_max_cook_time_minutes
    context_signals = state.get("context_signals") or {}
    meal_type = context_signals.get("meal_type")
    pantry_ingredients = _pantry_ingredient_names(state)

    messages: list[str] = []

    try:
        results, total_matched = await _search(
            runtime, dietary_filters, max_cook_time, cuisine, meal_type, pantry_ingredients
        )

        if results and meal_type is not None and total_matched < MIN_MEAL_TYPE_POOL:
            messages.append(
                f"[{NODE_NAME}] Only {total_matched} {meal_type}-appropriate recipe(s) exist, too few to "
                "filter on, so searching every meal type."
            )
            meal_type = None
            results, total_matched = await _search(
                runtime, dietary_filters, max_cook_time, cuisine, meal_type, pantry_ingredients
            )

        if not results:
            messages.append(
                f"[{NODE_NAME}] No recipes matched your exact request — trying with fewer constraints "
                "(dietary restrictions always stay in place)."
            )

            if meal_type is not None:
                messages.append(f"[{NODE_NAME}] Dropping the {meal_type} meal-type guess and trying again.")
                meal_type = None
                results, total_matched = await _search(
                    runtime, dietary_filters, max_cook_time, cuisine, meal_type, pantry_ingredients
                )

        if not results and max_cook_time is not None:
            raised = max(max_cook_time + 1, round(max_cook_time * COOK_TIME_RELAXATION_FACTOR))
            messages.append(
                f"[{NODE_NAME}] Still nothing — raising the cook-time limit from {max_cook_time} to "
                f"{raised} minutes and trying again."
            )
            max_cook_time = raised
            results, total_matched = await _search(
                runtime, dietary_filters, max_cook_time, cuisine, meal_type, pantry_ingredients
            )

        if not results and cuisine is not None:
            messages.append(
                f"[{NODE_NAME}] Still nothing — dropping the {cuisine} cuisine preference and trying again."
            )
            cuisine = None
            results, total_matched = await _search(
                runtime, dietary_filters, max_cook_time, cuisine, meal_type, pantry_ingredients
            )

        if results and (meal_type is not None or cuisine is not None):
            avoid_terms = list(unified.avoid_ingredients)
            avoid_dishes = list(unified.avoid_dishes)
            if not await _any_viable(runtime, state, results, avoid_terms, avoid_dishes, split.ingredient):
                # Non-empty but nothing cookable. Loosen what the system
                # guessed (meal type), then the soft preference (cuisine).
                # Dietary restrictions and a user-STATED cook time never move.
                trial_messages: list[str] = []
                trial_meal, trial_cuisine = meal_type, cuisine
                adopted: tuple[list[dict[str, Any]], int, str | None, str | None] | None = None
                for step in ("meal_type", "cuisine"):
                    if step == "meal_type" and trial_meal is not None:
                        trial_messages.append(
                            f"[{NODE_NAME}] Nothing in those {len(results)} recipe(s) can be cooked from "
                            f"your pantry — dropping the {trial_meal} meal-type guess."
                        )
                        trial_meal = None
                    elif step == "cuisine" and trial_cuisine is not None:
                        trial_messages.append(
                            f"[{NODE_NAME}] Nothing cookable among the {trial_cuisine} recipes — looking "
                            f"beyond {trial_cuisine} (a preference, not a requirement)."
                        )
                        trial_cuisine = None
                    else:
                        continue
                    trial_results, trial_total = await _search(
                        runtime, dietary_filters, max_cook_time, trial_cuisine, trial_meal, pantry_ingredients
                    )
                    if trial_results and await _any_viable(
                        runtime,
                        state,
                        trial_results,
                        avoid_terms,
                        avoid_dishes,
                        split.ingredient,
                        unified.dietary_restrictions,
                    ):
                        adopted = (trial_results, trial_total, trial_meal, trial_cuisine)
                        break
                if adopted is not None:
                    results, total_matched, meal_type, cuisine = adopted
                    messages.extend(trial_messages)
                else:
                    messages.append(
                        f"[{NODE_NAME}] Looked beyond the meal-type guess and cuisine preference too, and "
                        "still nothing in the pantry can make a matching recipe."
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
