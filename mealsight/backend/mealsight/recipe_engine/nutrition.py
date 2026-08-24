"""calculate_nutrition — sums per-ingredient nutrition for one recipe.

Deterministic, no LLM calls. Every ingredient is resolved to its
canonical name using the exact same normalizer and synonym resolution
the ingredient matcher uses (mealsight.matching), so "Chopped onion" and
a nutrition_reference row filed under "onion" connect the same way they
would during real pantry matching.

CRITICAL: coverage is reported on every result. If nutrition data only
exists for 6 of a recipe's 10 ingredients, the total is computed from
those 6 and labeled as partial — never presented as if it covered the
whole recipe. The three dietary tags (high_protein, low_carb,
low_calorie) are only ever applied when coverage exceeds 80%, since a
tag derived from incomplete data is actively misleading, worse than no
tag at all.
"""

from __future__ import annotations

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.recipe_engine.models import NutritionResult
from mealsight.recipe_engine.search import get_recipe

# Approximate, generic grams-per-unit conversions. Volume units are
# treated at roughly water density (1ml ≈ 1g) since this table has no
# per-ingredient density data — genuinely wrong for something like flour
# (lighter) or honey (heavier), but a deterministic, documented
# approximation is what's available without a much larger ingredient-
# density table this project doesn't have. Countable units use a single
# rough average weight for "one of that unit" — real cloves of garlic,
# cans, and so on vary, but this gives a consistent, explainable number
# rather than no number at all.
UNIT_TO_GRAMS: dict[str, float] = {
    "g": 1.0,
    "kg": 1000.0,
    "oz": 28.35,
    "lb": 453.6,
    "ml": 1.0,
    "l": 1000.0,
    "cup": 240.0,
    "tbsp": 15.0,
    "tsp": 5.0,
    "clove": 5.0,
    "can": 400.0,
    "slice": 25.0,
    "stick": 113.0,
    "piece": 100.0,
    "packet": 5.0,
    "bunch": 100.0,
    "dash": 0.5,
    "pinch": 0.3,
    "handful": 30.0,
}

# A bare count with no unit at all ("1 Onion") — one whole, unspecified
# item. A single rough average, same reasoning as the table above.
NO_UNIT_GRAMS = 100.0

MIN_COVERAGE_PCT_FOR_TAGS = 80.0

_NUTRITION_FIELDS = ("calories", "protein", "carbs", "fat", "fiber", "sodium")


def _quantity_to_grams(quantity: float | None, unit: str | None) -> float | None:
    if quantity is None:
        return None
    if unit is None:
        return quantity * NO_UNIT_GRAMS
    grams_per_unit = UNIT_TO_GRAMS.get(unit)
    if grams_per_unit is None:
        return None
    return quantity * grams_per_unit


async def calculate_nutrition(db: Database, recipe_id: str, servings: int) -> NutritionResult:
    """Sums per-ingredient nutrition for one recipe, divided by servings.
    Raises ValueError if no recipe with that id exists, or servings isn't
    a positive integer."""
    if servings <= 0:
        raise ValueError("servings must be a positive integer")

    recipe = await get_recipe(db, recipe_id)
    synonym_map = await load_synonym_map(db)

    totals = dict.fromkeys(_NUTRITION_FIELDS, 0.0)
    covered = 0
    total_ingredients = len(recipe.ingredients)

    for ingredient in recipe.ingredients:
        canonical = resolve_canonical(normalize_ingredient(ingredient.name), synonym_map)
        row = await db.fetch_one(
            "SELECT calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g, "
            "fiber_per_100g, sodium_per_100g FROM nutrition_reference WHERE ingredient = ?",
            (canonical,),
        )
        if row is None:
            continue

        grams = _quantity_to_grams(ingredient.quantity, ingredient.unit)
        if grams is None:
            continue

        covered += 1
        factor = grams / 100.0
        totals["calories"] += (row["calories_per_100g"] or 0.0) * factor
        totals["protein"] += (row["protein_per_100g"] or 0.0) * factor
        totals["carbs"] += (row["carbs_per_100g"] or 0.0) * factor
        totals["fat"] += (row["fat_per_100g"] or 0.0) * factor
        totals["fiber"] += (row["fiber_per_100g"] or 0.0) * factor
        totals["sodium"] += (row["sodium_per_100g"] or 0.0) * factor

    per_serving = {field: value / servings for field, value in totals.items()}
    coverage_pct = (covered / total_ingredients * 100) if total_ingredients else 0.0

    tags: list[str] = []
    if coverage_pct > MIN_COVERAGE_PCT_FOR_TAGS:
        if per_serving["protein"] > settings.high_protein_threshold_g:
            tags.append("high_protein")
        if per_serving["carbs"] < settings.low_carb_threshold_g:
            tags.append("low_carb")
        if per_serving["calories"] < settings.low_calorie_threshold:
            tags.append("low_calorie")

    if covered == total_ingredients and total_ingredients > 0:
        coverage_note = f"Nutrition calculated from all {total_ingredients} ingredients."
    else:
        coverage_note = (
            f"Nutrition calculated from {covered} of {total_ingredients} ingredients "
            f"({coverage_pct:.0f}% coverage) — totals likely understate the real values."
        )

    return NutritionResult(
        recipe_id=recipe.id,
        servings=servings,
        calories=round(per_serving["calories"], 1),
        protein_g=round(per_serving["protein"], 1),
        carbs_g=round(per_serving["carbs"], 1),
        fat_g=round(per_serving["fat"], 1),
        fiber_g=round(per_serving["fiber"], 1),
        sodium_mg=round(per_serving["sodium"], 1),
        ingredients_covered=covered,
        ingredients_total=total_ingredients,
        coverage_pct=round(coverage_pct, 1),
        tags=tags,
        coverage_note=coverage_note,
    )
