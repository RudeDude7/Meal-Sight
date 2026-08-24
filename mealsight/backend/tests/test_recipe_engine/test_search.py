"""Tests for mealsight.recipe_engine.search: search_recipes and
get_recipe, against hand-built rows in a throwaway recipes.db."""

from __future__ import annotations

import pytest

from mealsight.db.connection import Database
from mealsight.recipe_engine.search import get_recipe, search_recipes
from tests.test_recipe_engine.conftest import insert_recipe

_ONION = {"name": "onion", "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}


async def test_dietary_filter_excludes_recipes_missing_the_tag_not_just_deprioritizes(
    recipe_db: Database,
) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Vegan Stew",
        ingredients=[_ONION],
        cook_time_minutes=20,
        dietary_tags=["vegan", "vegetarian"],
    )
    await insert_recipe(
        recipe_db,
        recipe_id="2",
        name="Beef Stew",
        ingredients=[_ONION],
        cook_time_minutes=20,
        dietary_tags=[],
    )

    results = (await search_recipes(recipe_db, dietary_filters=["vegan"], max_cook_time=60)).results

    ids = {r.id for r in results}
    assert ids == {"1"}, (
        "a recipe missing the required tag must be excluded outright, not merely ranked lower"
    )


async def test_max_cook_time_excludes_recipes_over_limit_and_unknown_cook_time(
    recipe_db: Database,
) -> None:
    await insert_recipe(recipe_db, recipe_id="1", name="Quick", ingredients=[_ONION], cook_time_minutes=10)
    await insert_recipe(recipe_db, recipe_id="2", name="Slow", ingredients=[_ONION], cook_time_minutes=90)
    await insert_recipe(
        recipe_db, recipe_id="3", name="Unknown", ingredients=[_ONION], cook_time_minutes=None
    )

    results = (await search_recipes(recipe_db, dietary_filters=[], max_cook_time=30)).results

    ids = {r.id for r in results}
    assert ids == {"1"}


async def test_cuisine_and_meal_type_filters(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Italian Dinner",
        ingredients=[_ONION],
        cook_time_minutes=20,
        cuisine="Italian",
        meal_type="main",
    )
    await insert_recipe(
        recipe_db,
        recipe_id="2",
        name="Mexican Dinner",
        ingredients=[_ONION],
        cook_time_minutes=20,
        cuisine="Mexican",
        meal_type="main",
    )

    results = (
        await search_recipes(recipe_db, dietary_filters=[], max_cook_time=60, cuisine="Italian")
    ).results
    assert {r.id for r in results} == {"1"}

    results = (
        await search_recipes(recipe_db, dietary_filters=[], max_cook_time=60, meal_type="dessert")
    ).results
    assert results == []


async def test_max_results_caps_the_returned_list_but_total_matched_is_the_real_count(
    recipe_db: Database,
) -> None:
    for i in range(5):
        await insert_recipe(
            recipe_db, recipe_id=str(i), name=f"Recipe {i}", ingredients=[_ONION], cook_time_minutes=10
        )

    search_result = await search_recipes(recipe_db, dietary_filters=[], max_cook_time=60, max_results=2)

    assert len(search_result.results) == 2
    assert search_result.total_matched == 5


async def test_max_cook_time_none_does_not_filter_by_cook_time_at_all(recipe_db: Database) -> None:
    await insert_recipe(recipe_db, recipe_id="1", name="Quick", ingredients=[_ONION], cook_time_minutes=10)
    await insert_recipe(recipe_db, recipe_id="2", name="Slow", ingredients=[_ONION], cook_time_minutes=90)
    await insert_recipe(
        recipe_db, recipe_id="3", name="Unknown", ingredients=[_ONION], cook_time_minutes=None
    )

    search_result = await search_recipes(recipe_db, dietary_filters=[], max_cook_time=None)

    assert {r.id for r in search_result.results} == {"1", "2", "3"}


async def test_get_recipe_returns_full_detail(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db,
        recipe_id="1",
        name="Onion Soup",
        ingredients=[_ONION],
        steps=["Chop onion.", "Simmer."],
        cook_time_minutes=30,
        dietary_tags=["vegan"],
    )

    detail = await get_recipe(recipe_db, "1")

    assert detail.name == "Onion Soup"
    assert detail.steps == ["Chop onion.", "Simmer."]
    assert detail.dietary_tags == ["vegan"]
    assert len(detail.ingredients) == 1
    assert detail.ingredients[0].name == "onion"


async def test_get_recipe_raises_for_unknown_id(recipe_db: Database) -> None:
    with pytest.raises(ValueError, match="does-not-exist"):
        await get_recipe(recipe_db, "does-not-exist")
