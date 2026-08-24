"""Tests for mealsight.pantry.grocery: create_grocery_list and
get_grocery_list."""

from __future__ import annotations

from mealsight.db.connection import Database
from mealsight.pantry.grocery import (
    STAPLE_ITEMS,
    create_grocery_list,
    get_grocery_list,
    set_grocery_item_checked,
)
from mealsight.pantry.models import GroceryQuantity, MissingIngredientInput, RecipeMissingIngredients

_SYNONYMS = {"scallion": "green onion"}


def _recipe(recipe_id: str, name: str, ingredients: list[MissingIngredientInput]) -> RecipeMissingIngredients:
    return RecipeMissingIngredients(recipe_id=recipe_id, recipe_name=name, missing_ingredients=ingredients)


async def _seed_shelf_life(pantry_db: Database) -> None:
    for item_name, category in [
        ("garlic", "vegetable"),
        ("chicken", "protein"),
        ("milk", "dairy"),
        ("flour", "condiment"),  # deliberately not "grain" — proves section comes from the reference row
    ]:
        await pantry_db.execute(
            "INSERT INTO shelf_life_reference (item_name, category) VALUES (?, ?)", (item_name, category)
        )


async def test_duplicate_ingredients_across_recipes_collapse_to_one_line_with_combined_quantity(
    pantry_db: Database,
) -> None:
    await _seed_shelf_life(pantry_db)
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [MissingIngredientInput(name="garlic", quantity=2, unit="clove", importance="important")],
        ),
        _recipe(
            "2",
            "Recipe B",
            [MissingIngredientInput(name="garlic", quantity=3, unit="clove", importance="critical")],
        ),
    ]

    result = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})

    all_items = [item for section in result.sections for item in section.items]
    assert len(all_items) == 1
    garlic = all_items[0]
    assert garlic.name == "garlic"
    assert garlic.quantities == [GroceryQuantity(quantity=5.0, unit="clove")]
    assert set(garlic.needed_for) == {"Recipe A", "Recipe B"}
    assert garlic.importance == "critical"  # the more critical of the two recipes' requests wins


async def test_mismatched_units_stay_separate_rather_than_being_summed(pantry_db: Database) -> None:
    await _seed_shelf_life(pantry_db)
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [MissingIngredientInput(name="milk", quantity=1, unit="cup", importance="important")],
        ),
        _recipe(
            "2",
            "Recipe B",
            [MissingIngredientInput(name="milk", quantity=1, unit="l", importance="important")],
        ),
    ]

    result = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})

    all_items = [item for section in result.sections for item in section.items]
    milk = next(item for item in all_items if item.name == "milk")
    assert len(milk.quantities) == 2
    units = {q.unit for q in milk.quantities}
    assert units == {"cup", "l"}


async def test_staples_get_the_verify_flag(pantry_db: Database) -> None:
    await _seed_shelf_life(pantry_db)
    staple_name = next(iter(STAPLE_ITEMS))
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [MissingIngredientInput(name=staple_name, quantity=1, unit="count", importance="optional")],
        )
    ]

    result = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})

    all_items = [item for section in result.sections for item in section.items]
    assert all_items[0].is_staple is True
    assert all_items[0].verify_note is not None


async def test_non_staple_item_has_no_verify_flag(pantry_db: Database) -> None:
    await _seed_shelf_life(pantry_db)
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [MissingIngredientInput(name="chicken", quantity=1, unit="lb", importance="critical")],
        )
    ]

    result = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})

    all_items = [item for section in result.sections for item in section.items]
    assert all_items[0].is_staple is False
    assert all_items[0].verify_note is None


async def test_section_grouping_is_correct(pantry_db: Database) -> None:
    await _seed_shelf_life(pantry_db)
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [
                MissingIngredientInput(name="garlic", quantity=1, unit="clove", importance="important"),
                MissingIngredientInput(name="chicken", quantity=1, unit="lb", importance="critical"),
                MissingIngredientInput(name="milk", quantity=1, unit="cup", importance="important"),
                MissingIngredientInput(name="flour", quantity=1, unit="cup", importance="important"),
                MissingIngredientInput(name="unobtainium", quantity=1, unit="count", importance="optional"),
            ],
        )
    ]

    result = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})

    section_by_item = {item.name: section.section for section in result.sections for item in section.items}
    assert section_by_item["garlic"] == "produce"  # vegetable -> produce
    assert section_by_item["chicken"] == "protein"
    assert section_by_item["milk"] == "dairy"
    assert section_by_item["flour"] == "pantry"  # seeded as category "condiment" -> pantry
    assert section_by_item["unobtainium"] == "other"  # no shelf_life_reference row at all


async def test_synonym_differing_names_deduplicate_in_the_grocery_list(pantry_db: Database) -> None:
    await _seed_shelf_life(pantry_db)
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [MissingIngredientInput(name="scallions", quantity=1, unit="bunch", importance="important")],
        ),
        _recipe(
            "2",
            "Recipe B",
            [MissingIngredientInput(name="green onion", quantity=1, unit="bunch", importance="important")],
        ),
    ]

    result = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map=_SYNONYMS)

    all_items = [item for section in result.sections for item in section.items]
    assert len(all_items) == 1
    assert all_items[0].name == "green onion"
    assert all_items[0].quantities[0].quantity == 2.0


async def test_created_list_is_persisted_and_reloadable(pantry_db: Database) -> None:
    await _seed_shelf_life(pantry_db)
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [MissingIngredientInput(name="garlic", quantity=2, unit="clove", importance="important")],
        )
    ]

    created = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})
    reloaded = await get_grocery_list(list_id=created.id, pantry_db=pantry_db)

    assert reloaded is not None
    assert reloaded.id == created.id
    assert reloaded.status == "active"
    assert reloaded.sections == created.sections


async def test_get_grocery_list_defaults_to_the_most_recent_active_list(pantry_db: Database) -> None:
    await _seed_shelf_life(pantry_db)
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [MissingIngredientInput(name="garlic", quantity=1, unit="clove", importance="important")],
        )
    ]
    await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})
    second = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})

    most_recent = await get_grocery_list(pantry_db=pantry_db)

    assert most_recent is not None
    assert most_recent.id == second.id


async def test_get_grocery_list_with_no_lists_returns_none(pantry_db: Database) -> None:
    result = await get_grocery_list(pantry_db=pantry_db)
    assert result is None


async def test_get_grocery_list_unknown_id_returns_none(pantry_db: Database) -> None:
    result = await get_grocery_list(list_id=999, pantry_db=pantry_db)
    assert result is None


async def test_set_grocery_item_checked_marks_the_item(pantry_db: Database) -> None:
    await _seed_shelf_life(pantry_db)
    recipes = [
        _recipe(
            "1",
            "Recipe A",
            [MissingIngredientInput(name="garlic", quantity=1, unit="clove", importance="important")],
        )
    ]
    created = await create_grocery_list(recipes, pantry_db=pantry_db, synonym_map={})

    updated = await set_grocery_item_checked(
        created.id, "garlic", checked=True, pantry_db=pantry_db, synonym_map={}
    )

    assert updated is not None
    all_items = [item for section in updated.sections for item in section.items]
    assert all_items[0].checked is True

    reloaded = await get_grocery_list(list_id=created.id, pantry_db=pantry_db)
    assert reloaded is not None
    assert reloaded.sections[0].items[0].checked is True
