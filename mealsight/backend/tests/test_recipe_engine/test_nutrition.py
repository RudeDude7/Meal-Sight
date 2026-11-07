"""Tests for mealsight.recipe_engine.nutrition.calculate_nutrition."""

from __future__ import annotations

import pytest

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.recipe_engine.nutrition import calculate_nutrition
from tests.test_recipe_engine.conftest import insert_nutrition, insert_recipe


async def test_coverage_is_reported_and_labeled_partial(recipe_db: Database) -> None:
    await insert_nutrition(recipe_db, "chicken", calories=165, protein=31, carbs=0, fat=3.6)
    # "rice" deliberately has no nutrition row.
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=1,
        ingredients=[
            {
                "name": "chicken",
                "quantity": 100.0,
                "unit": "g",
                "importance": "critical",
                "raw_measure": "100g",
            },
            {
                "name": "rice",
                "quantity": 100.0,
                "unit": "g",
                "importance": "important",
                "raw_measure": "100g",
            },
        ],
    )

    result = await calculate_nutrition(recipe_db, "1", servings=1)

    assert result.ingredients_covered == 1
    assert result.ingredients_total == 2
    assert result.coverage_pct == 50.0
    assert "of 2 ingredients" in result.coverage_note
    assert "50%" in result.coverage_note


async def test_tags_suppressed_below_80_percent_coverage(recipe_db: Database) -> None:
    # A single, fully-covered, genuinely high-protein ingredient — but
    # three other ingredients have no nutrition data, dragging coverage
    # to 25%, well under the 80% bar tags require.
    await insert_nutrition(recipe_db, "chicken breast", calories=165, protein=31, carbs=0, fat=3.6)
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=1,
        ingredients=[
            {
                "name": "chicken breast",
                "quantity": 200.0,
                "unit": "g",
                "importance": "critical",
                "raw_measure": "200g",
            },
            {
                "name": "mystery a",
                "quantity": 100.0,
                "unit": "g",
                "importance": "important",
                "raw_measure": "100g",
            },
            {
                "name": "mystery b",
                "quantity": 100.0,
                "unit": "g",
                "importance": "important",
                "raw_measure": "100g",
            },
            {
                "name": "mystery c",
                "quantity": 100.0,
                "unit": "g",
                "importance": "important",
                "raw_measure": "100g",
            },
        ],
    )

    result = await calculate_nutrition(recipe_db, "1", servings=1)

    assert result.coverage_pct == 25.0
    assert result.protein_g > settings.high_protein_threshold_g  # the underlying value really is high
    assert result.tags == [], "a tag derived from incomplete data must be suppressed, not shown anyway"


async def test_tags_applied_when_coverage_exceeds_80_percent(recipe_db: Database) -> None:
    await insert_nutrition(recipe_db, "chicken breast", calories=165, protein=31, carbs=0, fat=3.6)
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=1,
        ingredients=[
            {
                "name": "chicken breast",
                "quantity": 200.0,
                "unit": "g",
                "importance": "critical",
                "raw_measure": "200g",
            },
        ],
    )

    result = await calculate_nutrition(recipe_db, "1", servings=1)

    assert result.coverage_pct == 100.0
    assert "high_protein" in result.tags


async def test_per_serving_values_do_not_depend_on_requested_servings(recipe_db: Database) -> None:
    await insert_nutrition(recipe_db, "rice", calories=130, protein=2.7, carbs=28.2, fat=0.3)
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=4,
        ingredients=[
            {
                "name": "rice",
                "quantity": 800.0,
                "unit": "g",
                "importance": "important",
                "raw_measure": "800g",
            },
        ],
    )

    # 800g rice for 4 servings = 1,040 kcal for the dish = 260 kcal per
    # serving, whether 1, 2 or 4 servings are requested. (Previously this
    # divided the base-quantity total by the REQUESTED servings, giving
    # 1,040 / 1 = 1,040 kcal "per serving" for a 1-serving request.)
    for requested in (1, 2, 4):
        result = await calculate_nutrition(recipe_db, "1", servings=requested)
        assert result.calories == 260.0, requested
        assert result.servings == requested


@pytest.mark.parametrize("servings_base", [1, 2, 4, 6])
async def test_per_serving_is_constant_across_servings_base_and_request(
    recipe_db: Database, servings_base: int
) -> None:
    await insert_nutrition(recipe_db, "rice", calories=130, protein=2.7, carbs=28.2, fat=0.3)
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=servings_base,
        ingredients=[
            {
                "name": "rice",
                "quantity": 200.0 * servings_base,
                "unit": "g",
                "importance": "important",
                "raw_measure": f"{200 * servings_base}g",
            },
        ],
    )

    # 200g of rice per base serving = 260 kcal per serving, always.
    results = [await calculate_nutrition(recipe_db, "1", servings=n) for n in (1, 2, 3, 4)]

    assert [r.calories for r in results] == [260.0, 260.0, 260.0, 260.0]


async def test_servings_base_one_recipe_is_unchanged_by_scaling(recipe_db: Database) -> None:
    await insert_nutrition(recipe_db, "rice", calories=130, protein=2.7, carbs=28.2, fat=0.3)
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Test",
        servings_base=1,
        ingredients=[
            {
                "name": "rice",
                "quantity": 200.0,
                "unit": "g",
                "importance": "important",
                "raw_measure": "200g",
            },
        ],
    )

    # One serving is 200g rice = 260 kcal; two servings is 400g, still
    # 260 kcal each.
    result = await calculate_nutrition(recipe_db, "1", servings=2)

    assert result.calories == 260.0
