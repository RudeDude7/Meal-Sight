"""Tests for mealsight.recipe_engine.reverse_search.get_recipe_by_ingredients."""

from __future__ import annotations

from mealsight.db.connection import Database
from mealsight.recipe_engine.reverse_search import get_recipe_by_ingredients

from .conftest import insert_recipe


def _ingredient(name: str) -> dict[str, object]:
    return {"name": name, "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}


async def test_ranks_proportional_use_of_the_supplied_list_above_recipe_own_coverage(
    recipe_db: Database,
) -> None:
    # small-recipe uses all 3 supplied ingredients out of its own 3 —
    # 100% of the supplied list. big-recipe uses those same 3
    # ingredients but has 12 total ingredients of its own — the OLD
    # pantry-overlap style denominator (recipe's own ingredient count)
    # would score big-recipe at 3/12=25%, far below small-recipe's
    # 3/3=100%, purely because it has more ingredients overall — this
    # tool's own denominator (supplied list size) scores BOTH at 100%,
    # since both use every supplied ingredient equally well.
    await insert_recipe(
        recipe_db,
        recipe_id="small-recipe",
        name="Small Recipe",
        ingredients=[_ingredient("egg"), _ingredient("flour"), _ingredient("milk")],
    )
    extra_ingredients = [_ingredient(f"extra-{i}") for i in range(9)]
    await insert_recipe(
        recipe_db,
        recipe_id="big-recipe",
        name="Big Recipe",
        ingredients=[_ingredient("egg"), _ingredient("flour"), _ingredient("milk"), *extra_ingredients],
    )

    result = await get_recipe_by_ingredients(
        recipe_db, ["egg", "flour", "milk"], minimum_match_percentage=0.0
    )

    by_id = {r.id: r for r in result.results}
    assert by_id["small-recipe"].match_percentage == 1.0
    assert by_id["big-recipe"].match_percentage == 1.0
    assert by_id["small-recipe"].recipe_ingredient_count == 3
    assert by_id["big-recipe"].recipe_ingredient_count == 12


async def test_a_recipe_using_fewer_of_the_supplied_ingredients_ranks_lower(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db, recipe_id="full-match", name="Full Match",
        ingredients=[_ingredient("egg"), _ingredient("flour"), _ingredient("milk")],
    )
    await insert_recipe(
        recipe_db, recipe_id="partial-match", name="Partial Match",
        ingredients=[_ingredient("egg"), _ingredient("cheese")],
    )

    result = await get_recipe_by_ingredients(
        recipe_db, ["egg", "flour", "milk"], minimum_match_percentage=0.0
    )

    assert [r.id for r in result.results] == ["full-match", "partial-match"]
    assert result.results[0].match_percentage == 1.0
    assert result.results[1].match_percentage == round(1 / 3, 10) or abs(
        result.results[1].match_percentage - 1 / 3
    ) < 1e-9


async def test_minimum_match_percentage_filters_recipes_below_it(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db, recipe_id="high", name="High", ingredients=[_ingredient("egg"), _ingredient("flour")]
    )
    await insert_recipe(recipe_db, recipe_id="low", name="Low", ingredients=[_ingredient("egg")])

    result = await get_recipe_by_ingredients(recipe_db, ["egg", "flour"], minimum_match_percentage=0.6)

    ids = {r.id for r in result.results}
    assert "high" in ids  # 2/2 = 1.0
    assert "low" not in ids  # 1/2 = 0.5, below 0.6


async def test_default_minimum_match_percentage_is_point_six(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db, recipe_id="borderline", name="Borderline",
        ingredients=[_ingredient("egg"), _ingredient("flour")],
    )
    # 2 of 3 supplied = 0.667, clears the documented default of 0.6.
    result = await get_recipe_by_ingredients(recipe_db, ["egg", "flour", "sugar"])
    assert any(r.id == "borderline" for r in result.results)


async def test_recipes_with_zero_overlap_are_excluded(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db, recipe_id="unrelated", name="Unrelated", ingredients=[_ingredient("chorizo")]
    )
    result = await get_recipe_by_ingredients(recipe_db, ["egg", "flour"], minimum_match_percentage=0.0)
    assert result.results == []


async def test_empty_ingredients_list_returns_empty_without_error(recipe_db: Database) -> None:
    await insert_recipe(recipe_db, recipe_id="r1", name="R1", ingredients=[_ingredient("egg")])
    result = await get_recipe_by_ingredients(recipe_db, [])
    assert result.results == []
    assert result.total_matched == 0


async def test_synonyms_resolve_to_the_same_canonical_ingredient(recipe_db: Database) -> None:
    await recipe_db.execute(
        "INSERT INTO ingredient_synonyms (canonical_name, synonym) VALUES ('green onion', 'scallion')"
    )
    await insert_recipe(
        recipe_db, recipe_id="r1", name="R1", ingredients=[_ingredient("scallions")]
    )
    result = await get_recipe_by_ingredients(recipe_db, ["green onion"], minimum_match_percentage=0.0)
    assert len(result.results) == 1
    assert result.results[0].match_percentage == 1.0


async def test_matched_ingredient_names_reflects_the_recipes_own_raw_names(recipe_db: Database) -> None:
    await insert_recipe(
        recipe_db, recipe_id="r1", name="R1",
        ingredients=[_ingredient("Chicken Breast"), _ingredient("Rice")],
    )
    result = await get_recipe_by_ingredients(
        recipe_db, ["chicken breast"], minimum_match_percentage=0.0
    )
    assert result.results[0].matched_ingredient_names == ["Chicken Breast"]
