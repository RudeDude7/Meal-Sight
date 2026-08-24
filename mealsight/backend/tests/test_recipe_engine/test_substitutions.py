"""Tests for mealsight.recipe_engine.substitutions.find_substitutions."""

from __future__ import annotations

from mealsight.db.connection import Database
from mealsight.recipe_engine.substitutions import find_substitutions
from tests.test_recipe_engine.conftest import insert_substitution


async def test_ranked_by_flavor_impact_minimal_first(recipe_db: Database) -> None:
    await insert_substitution(recipe_db, "butter", "margarine", flavor_impact="significant")
    await insert_substitution(recipe_db, "butter", "applesauce", flavor_impact="noticeable")
    await insert_substitution(recipe_db, "butter", "vegan margarine", flavor_impact="minimal")

    result = await find_substitutions(recipe_db, "butter", reason="unavailable")

    assert [s.substitute for s in result.suggestions] == [
        "vegan margarine",
        "applesauce",
        "margarine",
    ]


async def test_dietary_reason_with_dairy_free_constraint_excludes_dairy_substitutes(
    recipe_db: Database,
) -> None:
    await insert_substitution(recipe_db, "butter", "olive oil", flavor_impact="noticeable")
    await insert_substitution(recipe_db, "butter", "heavy cream", flavor_impact="minimal")

    result = await find_substitutions(
        recipe_db, "butter", reason="dietary", dietary_restrictions=["dairy_free"]
    )

    substitutes = [s.substitute for s in result.suggestions]
    assert "heavy cream" not in substitutes
    assert "olive oil" in substitutes
    assert result.excluded_count == 1


async def test_allergic_reason_with_nut_free_constraint_excludes_nut_substitutes(
    recipe_db: Database,
) -> None:
    await insert_substitution(recipe_db, "milk", "almond milk", flavor_impact="minimal")
    await insert_substitution(recipe_db, "milk", "oat milk", flavor_impact="noticeable")

    result = await find_substitutions(recipe_db, "milk", reason="allergic", dietary_restrictions=["nut_free"])

    substitutes = [s.substitute for s in result.suggestions]
    assert "almond milk" not in substitutes
    assert "oat milk" in substitutes


async def test_unavailable_reason_does_not_filter_by_dietary_restrictions(recipe_db: Database) -> None:
    await insert_substitution(recipe_db, "butter", "heavy cream", flavor_impact="minimal")

    result = await find_substitutions(
        recipe_db, "butter", reason="unavailable", dietary_restrictions=["dairy_free"]
    )

    assert [s.substitute for s in result.suggestions] == ["heavy cream"]
    assert result.excluded_count == 0


async def test_no_substitutions_found_returns_empty_list(recipe_db: Database) -> None:
    result = await find_substitutions(recipe_db, "unobtainium", reason="unavailable")

    assert result.suggestions == []
    assert result.excluded_count == 0
