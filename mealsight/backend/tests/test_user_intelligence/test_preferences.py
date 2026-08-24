"""Tests for mealsight.user_intelligence.preferences.update_preferences
and remove_preference."""

from __future__ import annotations

import pytest

from mealsight.db.connection import Database
from mealsight.user_intelligence.preferences import remove_preference, update_preferences

_SYNONYMS = {"scallion": "green onion"}


async def test_dietary_restrictions_append_and_deduplicate(user_db: Database) -> None:
    await update_preferences("dietary_restrictions", "vegan", user_db=user_db)
    profile = await update_preferences("dietary_restrictions", "vegan", user_db=user_db)

    assert profile.dietary_restrictions == ["vegan"]


async def test_dietary_restrictions_accept_a_list_and_accumulate_across_calls(user_db: Database) -> None:
    await update_preferences("dietary_restrictions", ["vegan"], user_db=user_db)
    profile = await update_preferences("dietary_restrictions", ["gluten_free"], user_db=user_db)

    assert profile.dietary_restrictions == ["vegan", "gluten_free"]


async def test_disliked_ingredients_append_and_deduplicate(user_db: Database) -> None:
    await update_preferences("disliked_ingredients", "cilantro", user_db=user_db, synonym_map={})
    profile = await update_preferences("disliked_ingredients", "cilantro", user_db=user_db, synonym_map={})

    assert profile.disliked_ingredients == ["cilantro"]


async def test_canonically_equivalent_dislikes_collapse_to_one_entry(user_db: Database) -> None:
    await update_preferences(
        "disliked_ingredients", "scallions", user_db=user_db, synonym_map=_SYNONYMS
    )
    profile = await update_preferences(
        "disliked_ingredients", "green onion", user_db=user_db, synonym_map=_SYNONYMS
    )

    assert profile.disliked_ingredients == ["green onion"]


async def test_scalar_fields_replace_rather_than_accumulate(user_db: Database) -> None:
    await update_preferences("household_size", 2, user_db=user_db)
    profile = await update_preferences("household_size", 4, user_db=user_db)

    assert profile.household_size == 4


async def test_cooking_skill_and_budget_sensitivity_replace(user_db: Database) -> None:
    profile = await update_preferences("cooking_skill", "advanced", user_db=user_db)
    profile = await update_preferences("budget_sensitivity", "budget", user_db=user_db)

    assert profile.cooking_skill == "advanced"
    assert profile.budget_sensitivity == "budget"


async def test_unknown_preference_type_is_rejected_naming_valid_options(user_db: Database) -> None:
    with pytest.raises(ValueError, match="household_size"):
        await update_preferences("favorite_color", "blue", user_db=user_db)


async def test_household_size_zero_is_rejected(user_db: Database) -> None:
    with pytest.raises(ValueError, match="household_size"):
        await update_preferences("household_size", 0, user_db=user_db)


async def test_preferred_cook_time_negative_is_rejected(user_db: Database) -> None:
    with pytest.raises(ValueError, match="preferred_cook_time_minutes"):
        await update_preferences("preferred_cook_time_minutes", -5, user_db=user_db)


async def test_cooking_skill_invalid_value_is_rejected_naming_accepted_values(user_db: Database) -> None:
    with pytest.raises(ValueError, match="beginner"):
        await update_preferences("cooking_skill", "expert", user_db=user_db)


async def test_budget_sensitivity_invalid_value_is_rejected_naming_accepted_values(
    user_db: Database,
) -> None:
    with pytest.raises(ValueError, match="moderate"):
        await update_preferences("budget_sensitivity", "cheap", user_db=user_db)


async def test_remove_dietary_restriction(user_db: Database) -> None:
    await update_preferences("dietary_restrictions", ["vegan", "gluten_free"], user_db=user_db)
    profile = await remove_preference("dietary_restrictions", "vegan", user_db=user_db)

    assert profile.dietary_restrictions == ["gluten_free"]


async def test_remove_disliked_ingredient_using_a_synonym_form(user_db: Database) -> None:
    await update_preferences(
        "disliked_ingredients", "scallions", user_db=user_db, synonym_map=_SYNONYMS
    )
    profile = await remove_preference(
        "disliked_ingredients", "green onion", user_db=user_db, synonym_map=_SYNONYMS
    )

    assert profile.disliked_ingredients == []


async def test_remove_preference_on_a_scalar_field_is_rejected(user_db: Database) -> None:
    with pytest.raises(ValueError, match="dietary_restrictions"):
        await remove_preference("household_size", "4", user_db=user_db)


async def test_remove_preference_absent_value_is_a_no_op(user_db: Database) -> None:
    await update_preferences("dietary_restrictions", "vegan", user_db=user_db)
    profile = await remove_preference("dietary_restrictions", "keto", user_db=user_db)

    assert profile.dietary_restrictions == ["vegan"]
