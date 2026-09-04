"""Converts mealsight.recipe_engine / mealsight.matching pydantic result
models into plain, JSON-serializable dicts with a stable shape — what
the recipe-engine MCP tools actually return — plus the structured error
shapes every tool returns instead of letting an exception escape.

Kept deliberately compact: these results enter an LLM's context window,
and one recommendation can mean many tool calls in a row, so
search_recipes in particular returns summaries only (no steps, no full
ingredient records) — get_recipe is the separate call for full detail.
"""

from __future__ import annotations

from typing import Any

from mealsight.matching.models import MatchResult
from mealsight.mcp_servers.errors import internal_error, not_found_error, validation_error
from mealsight.recipe_engine.models import (
    NutritionResult,
    RecipeDetail,
    ReverseSearchResults,
    ScaledRecipe,
    SearchResults,
    SubstitutionResult,
)

__all__ = [
    "internal_error",
    "match_result_to_dict",
    "not_found_error",
    "nutrition_result_to_dict",
    "recipe_detail_to_dict",
    "reverse_search_results_to_dict",
    "scaled_recipe_to_dict",
    "search_results_to_dict",
    "substitution_result_to_dict",
    "validation_error",
]


def search_results_to_dict(search_results: SearchResults) -> dict[str, Any]:
    """Shape: {"results": [{"id", "name", "cuisine", "meal_type",
    "cook_time_minutes", "dietary_tags"}, ...], "total_matched": int}.
    Compact summaries only — no ingredients, no steps. total_matched is
    the count before max_results capped the list; it can be larger than
    len(results)."""
    return {
        "results": [summary.model_dump(mode="json") for summary in search_results.results],
        "total_matched": search_results.total_matched,
    }


def recipe_detail_to_dict(detail: RecipeDetail) -> dict[str, Any]:
    """Shape: {"id", "name", "cuisine", "meal_type", "cook_time_minutes",
    "difficulty", "servings_base", "dietary_tags", "ingredients": [{"name",
    "quantity", "unit", "importance", "raw_measure"}, ...], "steps": [str,
    ...], "image_url"}. The full recipe — everything search_recipes
    deliberately omits."""
    return detail.model_dump(mode="json")


def match_result_to_dict(match_result: MatchResult) -> dict[str, Any]:
    """Shape: {"match_score", "can_cook", "matched_items", "substitutable_items",
    "partial_matches", "missing_items", "critical_missing", "summary"}.
    See mealsight.matching.models.MatchResult for each field's exact
    meaning; "summary" is a short, human-readable recap suitable for
    quoting directly."""
    return match_result.model_dump(mode="json")


def scaled_recipe_to_dict(scaled: ScaledRecipe) -> dict[str, Any]:
    """Shape: {"id", "name", "original_servings", "target_servings",
    "scale_factor", "ingredients": [{"name", "quantity_display", "unit",
    "importance"}, ...], "cook_time_minutes", "cook_time_adjusted",
    "cook_time_note"}. quantity_display is always a human-readable string
    ("1/4", "2"), never a raw float."""
    return scaled.model_dump(mode="json")


def nutrition_result_to_dict(nutrition: NutritionResult) -> dict[str, Any]:
    """Shape: {"recipe_id", "servings", "calories", "protein_g", "carbs_g",
    "fat_g", "fiber_g", "sodium_mg", "ingredients_covered",
    "ingredients_total", "coverage_pct", "tags", "coverage_note"}. Always
    check coverage_pct / coverage_note before treating the totals as
    complete — a result computed from partial ingredient data says so
    explicitly rather than silently looking whole."""
    return nutrition.model_dump(mode="json")


def reverse_search_results_to_dict(results: ReverseSearchResults) -> dict[str, Any]:
    """Shape: {"results": [{"id", "name", "cuisine", "meal_type",
    "cook_time_minutes", "match_percentage", "matched_ingredient_names",
    "recipe_ingredient_count"}, ...], "total_matched": int}.
    match_percentage is the fraction of the SUPPLIED ingredient list
    this recipe uses, not the recipe's own ingredient coverage — see
    mealsight.recipe_engine.reverse_search's own module docstring."""
    return {
        "results": [entry.model_dump(mode="json") for entry in results.results],
        "total_matched": results.total_matched,
    }


def substitution_result_to_dict(result: SubstitutionResult) -> dict[str, Any]:
    """Shape: {"ingredient", "reason", "suggestions": [{"substitute",
    "ratio", "flavor_impact", "notes"}, ...], "excluded_count"}.
    suggestions is already sorted minimal-flavor-impact first;
    excluded_count is how many candidates were filtered out by a dietary
    restriction (0 whenever reason isn't "allergic" or "dietary")."""
    return result.model_dump(mode="json")
