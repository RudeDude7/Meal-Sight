"""The ingredient matching engine — pure Python, deterministic, no LLM
calls anywhere. Given a recipe's ingredient list and what's actually
available (a pantry), decides whether the recipe is makeable, using the
substitutions and ingredient_synonyms reference tables seeded in
mealsight.seed.
"""

from mealsight.matching.matcher import (
    MatchContext,
    RecipeIngredientInput,
    build_match_context,
    match_recipe,
    match_recipe_by_id,
    parse_recipe_ingredients,
    substitute_satisfies_dietary_restrictions,
)
from mealsight.matching.models import (
    MatchedItem,
    MatchResult,
    MissingItem,
    PartialMatchItem,
    SubstitutableItem,
)
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.specificity import compare_specificity
from mealsight.matching.substitutions import SubstitutionOption, load_substitution_map
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical

__all__ = [
    "MatchContext",
    "MatchResult",
    "MatchedItem",
    "MissingItem",
    "PartialMatchItem",
    "RecipeIngredientInput",
    "SubstitutableItem",
    "SubstitutionOption",
    "build_match_context",
    "compare_specificity",
    "load_substitution_map",
    "load_synonym_map",
    "match_recipe",
    "match_recipe_by_id",
    "normalize_ingredient",
    "parse_recipe_ingredients",
    "resolve_canonical",
    "substitute_satisfies_dietary_restrictions",
]
