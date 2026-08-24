"""scale_recipe — adjusts ingredient quantities (and, past a threshold,
cook time) from a recipe's base serving count to a target serving count.

Deterministic, no LLM calls. The three rules that matter here:

  1. Quantities are always presented as human-readable measurements
     ("1/4 cup"), never raw decimals ("0.25 cups").
  2. Countable units (a clove of garlic, a can of tomatoes) round to a
     whole number, minimum 1 — you can't buy 0.375 cloves of garlic, and
     scaling down should never make a real ingredient disappear.
  3. To-taste and dash-style quantities (dash, pinch, handful, or no
     quantity at all) are left alone; there is nothing to scale.
"""

from __future__ import annotations

from fractions import Fraction

from mealsight.db.connection import Database
from mealsight.recipe_engine.models import ScaledIngredient, ScaledRecipe
from mealsight.recipe_engine.search import get_recipe

# Units that name a continuous, divisible measure — halving or doubling
# them produces another perfectly sensible measurement.
MEASURABLE_UNITS: frozenset[str] = frozenset({"tbsp", "tsp", "kg", "g", "ml", "l", "oz", "lb", "cup"})

# Units that name discrete, countable items — these round to a whole
# number after scaling, never a fraction of one.
COUNTABLE_UNITS: frozenset[str] = frozenset({"clove", "can", "slice", "stick", "piece", "packet", "bunch"})

# Left unscaled entirely: a "dash" or "pinch" is inherently a rough,
# to-taste amount, not a precise quantity meant to be multiplied.
NON_SCALING_UNITS: frozenset[str] = frozenset({"dash", "pinch", "handful"})

_FRACTION_DENOMINATOR_LIMIT = 8

# Cook time is only adjusted outside this scale-factor band — see
# _adjust_cook_time's docstring for why, and how.
_COOK_TIME_ADJUSTMENT_HIGH = 2.0
_COOK_TIME_ADJUSTMENT_LOW = 0.5


def _format_quantity(value: float) -> str:
    """Formats a scaled quantity as a human-readable mixed fraction
    ("1 1/2", "1/4", "2"), snapping to the nearest common cooking
    fraction (eighths or coarser) rather than showing a raw decimal."""
    fraction = Fraction(value).limit_denominator(_FRACTION_DENOMINATOR_LIMIT)
    whole, remainder_numerator = divmod(fraction.numerator, fraction.denominator)
    if remainder_numerator == 0:
        return str(whole)
    if whole == 0:
        return f"{remainder_numerator}/{fraction.denominator}"
    return f"{whole} {remainder_numerator}/{fraction.denominator}"


def _scale_quantity(quantity: float, unit: str | None, scale_factor: float) -> str:
    scaled = quantity * scale_factor
    if unit in COUNTABLE_UNITS or unit is None:
        return str(max(1, round(scaled)))
    return _format_quantity(scaled)


def _adjust_cook_time(cook_time_minutes: int, scale_factor: float) -> tuple[int, str]:
    """Cook time doesn't scale linearly with servings — doubling a recipe
    doesn't double how long it takes to cook, but a much larger or
    smaller batch does genuinely take somewhat more or less time (more
    mass to heat through, more surface area to brown, and so on). This
    applies a deliberately mild, sublinear adjustment (scale_factor to
    the power of 0.3) rather than pretending to compute a precise new
    time — it's a heuristic, not a physical simulation, and is only
    applied at all when the scale factor is large enough to matter."""
    adjusted = round(cook_time_minutes * (scale_factor**0.3))
    note = (
        f"Recipe scaled {scale_factor:.2g}x — cook time adjusted from "
        f"{cook_time_minutes} to approximately {adjusted} minutes; treat this as a "
        f"rough estimate, not a precise figure."
    )
    return adjusted, note


async def scale_recipe(db: Database, recipe_id: str, target_servings: int) -> ScaledRecipe:
    """Scales a recipe's ingredient quantities from its base servings to
    target_servings. Raises ValueError if no recipe with that id exists,
    or if target_servings isn't a positive integer."""
    if target_servings <= 0:
        raise ValueError("target_servings must be a positive integer")

    recipe = await get_recipe(db, recipe_id)
    scale_factor = target_servings / recipe.servings_base

    scaled_ingredients: list[ScaledIngredient] = []
    for ingredient in recipe.ingredients:
        if ingredient.unit in NON_SCALING_UNITS or ingredient.quantity is None:
            scaled_ingredients.append(
                ScaledIngredient(
                    name=ingredient.name,
                    quantity_display=(
                        _format_quantity(ingredient.quantity) if ingredient.quantity is not None else None
                    ),
                    unit=ingredient.unit,
                    importance=ingredient.importance,
                )
            )
            continue

        display = _scale_quantity(ingredient.quantity, ingredient.unit, scale_factor)
        scaled_ingredients.append(
            ScaledIngredient(
                name=ingredient.name,
                quantity_display=display,
                unit=ingredient.unit,
                importance=ingredient.importance,
            )
        )

    cook_time_adjusted = False
    cook_time_note: str | None = None
    cook_time_minutes = recipe.cook_time_minutes
    if recipe.cook_time_minutes is not None and (
        scale_factor > _COOK_TIME_ADJUSTMENT_HIGH or scale_factor < _COOK_TIME_ADJUSTMENT_LOW
    ):
        cook_time_minutes, cook_time_note = _adjust_cook_time(recipe.cook_time_minutes, scale_factor)
        cook_time_adjusted = True

    return ScaledRecipe(
        id=recipe.id,
        name=recipe.name,
        original_servings=recipe.servings_base,
        target_servings=target_servings,
        scale_factor=round(scale_factor, 4),
        ingredients=scaled_ingredients,
        cook_time_minutes=cook_time_minutes,
        cook_time_adjusted=cook_time_adjusted,
        cook_time_note=cook_time_note,
    )
