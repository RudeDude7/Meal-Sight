"""Tests for mealsight.recipe_engine.scaling.scale_recipe."""

from __future__ import annotations

import pytest

from mealsight.db.connection import Database
from mealsight.recipe_engine.scaling import scale_recipe
from tests.test_recipe_engine.conftest import insert_recipe


async def test_scaling_produces_a_fraction_not_a_decimal(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=4,
        ingredients=[
            {
                "name": "flour",
                "quantity": 1.0,
                "unit": "cup",
                "importance": "important",
                "raw_measure": "1 cup",
            }
        ],
    )

    scaled = await scale_recipe(recipe_db, "1", target_servings=2)

    assert scaled.ingredients[0].quantity_display == "1/2"
    assert scaled.ingredients[0].unit == "cup"


async def test_countable_item_never_scales_to_a_fraction(recipe_db: Database) -> None:
    # 1.5 cloves at servings_base=4, scaled to 1 serving: 1.5 * 0.25 = 0.375
    # — must round to a whole clove, never "3/8".
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=4,
        ingredients=[
            {
                "name": "garlic",
                "quantity": 1.5,
                "unit": "clove",
                "importance": "important",
                "raw_measure": "1 1/2 cloves",
            }
        ],
    )

    scaled = await scale_recipe(recipe_db, "1", target_servings=1)

    assert scaled.ingredients[0].quantity_display == "1"
    assert "/" not in scaled.ingredients[0].quantity_display


async def test_bare_count_with_no_unit_rounds_to_whole(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=4,
        ingredients=[
            {"name": "onion", "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}
        ],
    )

    scaled = await scale_recipe(recipe_db, "1", target_servings=8)

    assert scaled.ingredients[0].quantity_display == "2"


async def test_to_taste_and_dash_quantities_are_left_unscaled(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=4,
        ingredients=[
            {
                "name": "salt",
                "quantity": None,
                "unit": None,
                "importance": "optional",
                "raw_measure": "to taste",
            },
            {
                "name": "cinnamon",
                "quantity": 1.0,
                "unit": "dash",
                "importance": "optional",
                "raw_measure": "1 dash",
            },
        ],
    )

    scaled = await scale_recipe(recipe_db, "1", target_servings=12)

    salt, cinnamon = scaled.ingredients
    assert salt.quantity_display is None
    assert cinnamon.quantity_display == "1"
    assert cinnamon.unit == "dash"


async def test_cook_time_unadjusted_within_the_normal_scaling_band(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=4,
        cook_time_minutes=30,
        ingredients=[
            {"name": "onion", "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}
        ],
    )

    # scale factor 1.5 — within [0.5, 2.0], no adjustment.
    scaled = await scale_recipe(recipe_db, "1", target_servings=6)

    assert scaled.cook_time_adjusted is False
    assert scaled.cook_time_minutes == 30
    assert scaled.cook_time_note is None


async def test_cook_time_adjusted_above_2x_scale_factor(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=4,
        cook_time_minutes=30,
        ingredients=[
            {"name": "onion", "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}
        ],
    )

    # scale factor 3.0 — above the 2.0x threshold.
    scaled = await scale_recipe(recipe_db, "1", target_servings=12)

    assert scaled.cook_time_adjusted is True
    assert scaled.cook_time_minutes != 30
    assert scaled.cook_time_note is not None


async def test_raises_for_non_positive_target_servings(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=4,
        ingredients=[
            {"name": "onion", "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}
        ],
    )

    with pytest.raises(ValueError):
        await scale_recipe(recipe_db, "1", target_servings=0)
