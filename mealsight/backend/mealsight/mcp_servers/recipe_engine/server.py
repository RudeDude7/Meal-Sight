"""The recipe-engine MCP server: a thin FastMCP transport shell over
mealsight.recipe_engine and mealsight.matching. Every tool here validates
its own input, calls straight into an existing, independently-tested
function, and serializes the result (mealsight.mcp_servers.recipe_engine.
serialization) — no matching, scaling, or nutrition logic is
reimplemented in this file. If a rule about what a recipe or a match
means ever needs to change, it changes in the underlying module, not
here.

Deterministic, no LLM calls anywhere in this module either.
"""

from __future__ import annotations

from typing import Any, get_args

from fastmcp import FastMCP

from mealsight.db import get_recipe_db
from mealsight.matching import match_recipe_by_id
from mealsight.mcp_servers.recipe_engine.serialization import (
    internal_error,
    match_result_to_dict,
    not_found_error,
    nutrition_result_to_dict,
    recipe_detail_to_dict,
    reverse_search_results_to_dict,
    scaled_recipe_to_dict,
    search_results_to_dict,
    substitution_result_to_dict,
    validation_error,
)
from mealsight.recipe_engine import calculate_nutrition as _calculate_nutrition
from mealsight.recipe_engine import find_substitutions as _find_substitutions
from mealsight.recipe_engine import get_recipe as _get_recipe
from mealsight.recipe_engine import get_recipe_by_ingredients as _get_recipe_by_ingredients
from mealsight.recipe_engine import scale_recipe as _scale_recipe
from mealsight.recipe_engine import search_recipes as _search_recipes
from mealsight.recipe_engine.models import SubstitutionReason
from mealsight.recipe_engine.reverse_search import DEFAULT_MINIMUM_MATCH_PERCENTAGE
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.mcp_servers.recipe_engine")

mcp: FastMCP[Any] = FastMCP("recipe-engine")

_SUBSTITUTION_REASONS: tuple[str, ...] = get_args(SubstitutionReason)


@mcp.tool
async def search_recipes(
    dietary_filters: list[str] | None = None,
    max_cook_time: int | None = None,
    cuisine: str | None = None,
    meal_type: str | list[str] | None = None,
    max_results: int = 20,
    pantry_ingredients: list[str] | None = None,
) -> dict[str, Any]:
    """Searches the recipe database by hard filters and returns compact
    summaries (id, name, cuisine, meal_type, cook_time_minutes,
    dietary_tags) — NOT full recipes and NOT ingredient-matched against
    any pantry (pantry_ingredients only pre-RANKS the returned order; see
    below — call match_ingredients separately for a real, scored match
    against a specific pantry). Use this first to find candidate
    recipes; call get_recipe for full detail on one of them.

    dietary_filters (e.g. ["vegan", "gluten_free"]) is a hard constraint:
    a recipe missing even one requested tag is excluded outright, never
    just ranked lower — there is no "close enough" match here. Omit
    max_cook_time to skip filtering on cook time entirely; when set, any
    recipe with an unknown cook time is also excluded, since there is no
    way to confirm it meets the limit.

    meal_type accepts either one exact value ("dessert") or a list of
    acceptable values (["main", "side"]) — a recipe matches if its own
    meal_type is any one of them.

    pantry_ingredients, when given, pre-ranks the returned order by a
    cheap ingredient-overlap heuristic (fraction of the recipe's own
    ingredients found in the pantry) BEFORE max_results caps the list —
    this is what keeps a genuinely cookable recipe with a late-alphabet
    name from being cut off before anything ever scores it properly.
    Omit it for a plain browsing search with no pantry context, which
    returns alphabetical order as before.

    Returns {"results": [...], "total_matched": int}. total_matched is
    how many recipes satisfied every filter BEFORE max_results capped the
    list — it can be larger than len(results), and is the number to
    report when saying how many recipes matched (e.g. "there are 47
    dairy-free recipes under 30 minutes; here are the first 20").
    """
    dietary_filters = dietary_filters or []
    try:
        db = get_recipe_db()
        result = await _search_recipes(
            db,
            dietary_filters=dietary_filters,
            max_cook_time=max_cook_time,
            cuisine=cuisine,
            meal_type=meal_type,
            max_results=max_results,
            pantry_ingredients=pantry_ingredients,
        )
        return search_results_to_dict(result)
    except Exception:
        logger.error("search_recipes_failed", exc_info=True, max_results=max_results)
        return internal_error()


@mcp.tool
async def get_recipe(recipe_id: str) -> dict[str, Any]:
    """Fetches one recipe in full: every ingredient (name, quantity,
    unit, importance, raw_measure), every instruction step in order,
    cook time, difficulty, servings_base, dietary_tags, and image_url.
    Use this once a specific recipe_id has been chosen (from
    search_recipes or elsewhere) and full detail is actually needed —
    search_recipes intentionally does not return this much per recipe,
    to keep result lists compact.

    Returns a structured {"error": "not_found", ...} result, not an
    exception, if recipe_id doesn't exist.
    """
    try:
        db = get_recipe_db()
        detail = await _get_recipe(db, recipe_id)
        return recipe_detail_to_dict(detail)
    except ValueError:
        return not_found_error("recipe", recipe_id)
    except Exception:
        logger.error("get_recipe_failed", exc_info=True, recipe_id=recipe_id)
        return internal_error()


@mcp.tool
async def match_ingredients(
    recipe_id: str,
    available_ingredients: list[str],
    dietary_restrictions: list[str] | None = None,
) -> dict[str, Any]:
    """Checks whether a specific recipe is actually makeable with a given
    list of available ingredients (a pantry, or whatever a vision model
    just identified in a photo) — this is the ingredient-matching step
    search_recipes deliberately does NOT do. Call this after choosing a
    recipe_id, passing in what's actually on hand.

    Returns match_score (0.0-1.0), can_cook (a bool — true only when the
    score clears the configured threshold AND no critical ingredient is
    missing, so it can be false even at a moderately high score),
    matched_items, substitutable_items (a table-driven swap, e.g. olive
    oil for butter), partial_matches (the pantry has a less-specific
    form of what's needed, e.g. plain "chicken" when the recipe wants
    "chicken thighs" — usable, but possibly not the exact cut wanted),
    missing_items, critical_missing (a shortlist of just the missing
    ingredients that block cooking entirely), and a human-readable
    summary. dietary_restrictions (e.g. ["dairy_free"]) excludes any
    substitute that itself violates the restriction — it does not affect
    matched_items, since an ingredient already on hand is the user's own
    to decide about.

    Returns a structured {"error": "not_found", ...} result, not an
    exception, if recipe_id doesn't exist.
    """
    dietary_restrictions = dietary_restrictions or []
    try:
        db = get_recipe_db()
        result = await match_recipe_by_id(
            db, recipe_id, available_ingredients, dietary_restrictions=dietary_restrictions
        )
        return match_result_to_dict(result)
    except ValueError:
        return not_found_error("recipe", recipe_id)
    except Exception:
        logger.error("match_ingredients_failed", exc_info=True, recipe_id=recipe_id)
        return internal_error()


@mcp.tool
async def scale_recipe(recipe_id: str, target_servings: int) -> dict[str, Any]:
    """Scales a recipe's ingredient quantities from its base serving
    count to target_servings, formatted for a human to read directly
    (e.g. "1/4 cup", never "0.25 cups"; countable items like garlic
    cloves round to a whole number, minimum 1, never a fraction of one;
    to-taste/dash amounts are left unscaled since there is nothing
    numeric to multiply). Use this whenever a recipe needs to be
    resized — it does not affect nutrition totals per serving, which
    calculate_nutrition already reports independent of serving count.

    cook_time_minutes is only adjusted (with cook_time_adjusted=true and
    an explanatory cook_time_note) when the scale factor is above 2x or
    below 0.5x — otherwise cook time is left as-is and cook_time_adjusted
    is false.

    Returns a structured {"error": "not_found", ...} result if recipe_id
    doesn't exist, or {"error": "validation_error", ...} naming
    target_servings if it isn't a positive integer.
    """
    if target_servings <= 0:
        return validation_error(
            "target_servings",
            f"target_servings must be a positive integer, got {target_servings}.",
        )
    try:
        db = get_recipe_db()
        scaled = await _scale_recipe(db, recipe_id, target_servings)
        return scaled_recipe_to_dict(scaled)
    except ValueError:
        return not_found_error("recipe", recipe_id)
    except Exception:
        logger.error("scale_recipe_failed", exc_info=True, recipe_id=recipe_id)
        return internal_error()


@mcp.tool
async def calculate_nutrition(recipe_id: str, servings: int) -> dict[str, Any]:
    """Sums per-ingredient nutrition (calories, protein, carbs, fat,
    fiber, sodium) for one recipe, divided by servings. ALWAYS check
    ingredients_covered/ingredients_total/coverage_pct/coverage_note
    before treating the totals as complete or applying them to a
    recommendation — a result built from partial ingredient data says so
    explicitly (e.g. "calculated from 6 of 10 ingredients") rather than
    silently looking whole. The tags list (high_protein, low_carb,
    low_calorie) is only ever populated when coverage exceeds 80%; below
    that, tags is always empty, deliberately, even if the underlying
    numbers would otherwise qualify.

    Returns a structured {"error": "not_found", ...} result if recipe_id
    doesn't exist, or {"error": "validation_error", ...} naming servings
    if it isn't a positive integer.
    """
    if servings <= 0:
        return validation_error("servings", f"servings must be a positive integer, got {servings}.")
    try:
        db = get_recipe_db()
        nutrition = await _calculate_nutrition(db, recipe_id, servings)
        return nutrition_result_to_dict(nutrition)
    except ValueError:
        return not_found_error("recipe", recipe_id)
    except Exception:
        logger.error("calculate_nutrition_failed", exc_info=True, recipe_id=recipe_id)
        return internal_error()


@mcp.tool
async def find_substitutions(ingredient_name: str, reason: str = "unavailable") -> dict[str, Any]:
    """Suggests substitutes for one ingredient, ranked minimal
    flavor-impact first. Use this when match_ingredients reports a
    missing (or partially-matched) ingredient and a stand-in is needed,
    or whenever a user asks "what can I use instead of X".

    reason must be one of "unavailable", "allergic", "dietary", or
    "dislike" — it is recorded on the result for context only. IMPORTANT:
    this tool does NOT take a specific allergen or diet to filter
    against, so passing reason="allergic" or reason="dietary" here does
    NOT exclude any substitute on its own — it only labels the result.
    For an actual hard exclusion (e.g. "no dairy substitutes"), use
    match_ingredients instead and pass dietary_restrictions there; it
    applies the identical exclusion rule to every substitute it
    considers.

    Returns a structured {"error": "validation_error", ...} naming the
    accepted reason values if reason isn't one of them.
    """
    if reason not in _SUBSTITUTION_REASONS:
        return validation_error(
            "reason",
            f"{reason!r} is not a recognized reason.",
            accepted=list(_SUBSTITUTION_REASONS),
        )
    try:
        db = get_recipe_db()
        result = await _find_substitutions(db, ingredient_name, reason)  # type: ignore[arg-type]
        return substitution_result_to_dict(result)
    except Exception:
        logger.error("find_substitutions_failed", exc_info=True, ingredient_name=ingredient_name)
        return internal_error()


@mcp.tool
async def get_recipe_by_ingredients(
    ingredients: list[str], minimum_match_percentage: float = DEFAULT_MINIMUM_MATCH_PERCENTAGE
) -> dict[str, Any]:
    """Reverse search: given a list of ingredients (typically the
    pantry), returns recipes ranked by how well they use THAT LIST —
    the opposite direction from search_recipes (which filters by
    constraints, then optionally pre-ranks by pantry overlap). Use this
    for "what can I make with what I have" rather than "show me recipes
    matching these filters."

    match_percentage is the fraction of ingredients (not the recipe's
    own ingredient list) that a recipe actually uses — a recipe using
    3 of 3 supplied ingredients scores 1.0 and ranks above one using
    those same 3 ingredients out of its own 12, since from the caller's
    point of view both used everything supplied equally well. Only
    recipes at or above minimum_match_percentage (default 0.6) are
    returned at all, ranked highest match_percentage first.

    An empty ingredients list returns an empty result immediately.

    Returns {"results": [{"id", "name", "cuisine", "meal_type",
    "cook_time_minutes", "match_percentage", "matched_ingredient_names",
    "recipe_ingredient_count"}, ...], "total_matched": int}.

    Returns a structured {"error": "validation_error", ...} naming
    minimum_match_percentage if it isn't between 0.0 and 1.0.
    """
    if not (0.0 <= minimum_match_percentage <= 1.0):
        return validation_error(
            "minimum_match_percentage",
            f"minimum_match_percentage must be between 0.0 and 1.0, got {minimum_match_percentage}.",
        )
    try:
        db = get_recipe_db()
        result = await _get_recipe_by_ingredients(db, ingredients, minimum_match_percentage)
        return reverse_search_results_to_dict(result)
    except Exception:
        logger.error("get_recipe_by_ingredients_failed", exc_info=True, ingredient_count=len(ingredients))
        return internal_error()
