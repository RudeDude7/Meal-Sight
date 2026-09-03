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


async def test_pantry_overlap_ranks_a_late_alphabet_cookable_recipe_ahead_of_early_alphabet_junk(
    recipe_db: Database,
) -> None:
    """The phase 6.4 finding, reproduced directly: with no pantry-aware
    ranking, an alphabetically-early recipe with zero real ingredient
    overlap would sit ahead of a genuinely cookable, late-alphabet one
    purely because of its name. pantry_ingredients must put the high-
    overlap recipe first regardless of name."""
    peanut_butter = {
        "name": "peanut butter",
        "quantity": 1.0,
        "unit": "cup",
        "importance": "critical",
        "raw_measure": "1 cup",
    }
    sugar = {
        "name": "sugar",
        "quantity": 1.0,
        "unit": "cup",
        "importance": "important",
        "raw_measure": "1 cup",
    }
    egg = {"name": "egg", "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}
    unrelated = {
        "name": "saffron",
        "quantity": 1.0,
        "unit": "pinch",
        "importance": "critical",
        "raw_measure": "pinch",
    }

    # Alphabetically first, zero real overlap with the pantry below.
    await insert_recipe(
        recipe_db, recipe_id="1", name="Apple Saffron Rice", ingredients=[unrelated], cook_time_minutes=20
    )
    await insert_recipe(
        recipe_db, recipe_id="2", name="Beet Saffron Soup", ingredients=[unrelated], cook_time_minutes=20
    )
    # Alphabetically last, but every ingredient is in the pantry.
    await insert_recipe(
        recipe_db,
        recipe_id="3",
        name="Zzz Peanut Butter Cookies",
        ingredients=[peanut_butter, sugar, egg],
        cook_time_minutes=20,
    )

    pantry = ["peanut butter", "sugar", "egg"]

    without_pantry = await search_recipes(recipe_db, dietary_filters=[], max_results=10)
    assert [r.id for r in without_pantry.results] == ["1", "2", "3"], (
        "sanity check: with no pantry context, order stays alphabetical"
    )

    with_pantry = await search_recipes(
        recipe_db, dietary_filters=[], max_results=2, pantry_ingredients=pantry
    )
    ids = [r.id for r in with_pantry.results]
    assert "3" in ids, "the fully-cookable, late-alphabet recipe must survive the cap"
    assert ids[0] == "3", "it must rank ahead of the two zero-overlap recipes, not just survive"


async def test_pantry_overlap_ranking_does_not_change_total_matched(recipe_db: Database) -> None:
    """total_matched must still report the true pre-cap count — pantry-
    overlap ranking changes ORDER, never how many recipes matched the
    hard filters in the first place."""
    ingredient = {
        "name": "flour",
        "quantity": 1.0,
        "unit": "cup",
        "importance": "important",
        "raw_measure": "1 cup",
    }
    for i in range(5):
        await insert_recipe(
            recipe_db, recipe_id=str(i), name=f"Recipe {i}", ingredients=[ingredient], cook_time_minutes=10
        )

    result = await search_recipes(
        recipe_db, dietary_filters=[], max_results=2, pantry_ingredients=["flour"]
    )

    assert len(result.results) == 2
    assert result.total_matched == 5


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
