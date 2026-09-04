"""The Recipe Engine — plain Python tools over the local recipes table:
search, detail lookup, serving scaling, nutrition totals, and ingredient
substitution lookup. All deterministic, no LLM calls anywhere. Wrapped
as MCP tools in mealsight.mcp_servers.recipe_engine, but also callable
directly.
"""

from mealsight.recipe_engine.models import (
    NutritionResult,
    RecipeDetail,
    RecipeIngredient,
    RecipeSummary,
    ReverseMatchedRecipe,
    ReverseSearchResults,
    ScaledIngredient,
    ScaledRecipe,
    SearchResults,
    SubstitutionReason,
    SubstitutionResult,
    SubstitutionSuggestion,
)
from mealsight.recipe_engine.nutrition import calculate_nutrition
from mealsight.recipe_engine.reverse_search import (
    DEFAULT_MINIMUM_MATCH_PERCENTAGE,
    get_recipe_by_ingredients,
)
from mealsight.recipe_engine.scaling import scale_recipe
from mealsight.recipe_engine.search import get_recipe, search_recipes
from mealsight.recipe_engine.substitutions import find_substitutions

__all__ = [
    "DEFAULT_MINIMUM_MATCH_PERCENTAGE",
    "NutritionResult",
    "RecipeDetail",
    "RecipeIngredient",
    "RecipeSummary",
    "ReverseMatchedRecipe",
    "ReverseSearchResults",
    "ScaledIngredient",
    "ScaledRecipe",
    "SearchResults",
    "SubstitutionReason",
    "SubstitutionResult",
    "SubstitutionSuggestion",
    "calculate_nutrition",
    "find_substitutions",
    "get_recipe",
    "get_recipe_by_ingredients",
    "scale_recipe",
    "search_recipes",
]
