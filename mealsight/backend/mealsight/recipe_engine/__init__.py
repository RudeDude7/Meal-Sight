"""The Recipe Engine — plain Python tools over the local recipes table:
search, detail lookup, serving scaling, nutrition totals, and ingredient
substitution lookup. All deterministic, no LLM calls anywhere. No MCP
wrapper yet — these are called directly for now.
"""

from mealsight.recipe_engine.models import (
    NutritionResult,
    RecipeDetail,
    RecipeIngredient,
    RecipeSummary,
    ScaledIngredient,
    ScaledRecipe,
    SubstitutionReason,
    SubstitutionResult,
    SubstitutionSuggestion,
)
from mealsight.recipe_engine.nutrition import calculate_nutrition
from mealsight.recipe_engine.scaling import scale_recipe
from mealsight.recipe_engine.search import get_recipe, search_recipes
from mealsight.recipe_engine.substitutions import find_substitutions

__all__ = [
    "NutritionResult",
    "RecipeDetail",
    "RecipeIngredient",
    "RecipeSummary",
    "ScaledIngredient",
    "ScaledRecipe",
    "SubstitutionReason",
    "SubstitutionResult",
    "SubstitutionSuggestion",
    "calculate_nutrition",
    "find_substitutions",
    "get_recipe",
    "scale_recipe",
    "search_recipes",
]
