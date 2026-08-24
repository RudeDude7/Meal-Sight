"""Tests for mealsight.matching.matcher.match_recipe: scoring arithmetic,
can_cook rules, and dietary-constrained substitution eligibility. No live
API, no LLM, no database — every case here is constructed by hand."""

from __future__ import annotations

from mealsight.config.settings import settings
from mealsight.matching.matcher import RecipeIngredientInput, match_recipe
from mealsight.matching.models import Importance
from mealsight.matching.substitutions import SubstitutionOption

_NO_SUBS: dict[str, list[SubstitutionOption]] = {}
_NO_SYNONYMS: dict[str, str] = {}


def _ingredient(name: str, importance: Importance) -> RecipeIngredientInput:
    return RecipeIngredientInput(name=name, importance=importance)


def test_full_match_scores_one_and_can_cook() -> None:
    recipe = [
        _ingredient("onion", "important"),
        _ingredient("garlic", "important"),
        _ingredient("chicken", "critical"),
    ]
    pantry = ["onion", "garlic", "chicken"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert len(result.matched_items) == 3
    assert result.substitutable_items == []
    assert result.missing_items == []
    assert result.match_score == 1.0
    assert result.can_cook is True


def test_one_critical_missing_forces_can_cook_false_even_above_threshold() -> None:
    # 10 ingredients, 9 matched, 1 critical missing.
    # base = 9/10 = 0.9; penalty = 0.3 * 1 = 0.3; score = 0.6 >= 0.5,
    # but a missing critical ingredient must still force can_cook False.
    recipe = [_ingredient(f"item{i}", "important") for i in range(9)]
    recipe.append(_ingredient("saffron", "critical"))
    pantry = [f"item{i}" for i in range(9)]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert result.critical_missing == ["saffron"]
    assert result.match_score == 0.6
    assert result.can_cook is False


def test_several_optional_missing_still_allows_can_cook_true() -> None:
    # 5 ingredients, 3 matched (important), 2 missing (optional).
    # base = 3/5 = 0.6, no critical missing -> can_cook True.
    recipe = [
        _ingredient("rice", "important"),
        _ingredient("soy sauce", "important"),
        _ingredient("chicken", "important"),
        _ingredient("green onion", "optional"),
        _ingredient("sesame seed", "optional"),
    ]
    pantry = ["rice", "soy sauce", "chicken"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert result.match_score == 0.6
    assert result.critical_missing == []
    assert result.can_cook is True
    assert {item.name for item in result.missing_items} == {"green onion", "sesame seed"}
    assert all(item.importance == "optional" for item in result.missing_items)


def test_zero_ingredient_recipe_scores_zero_without_dividing_by_zero() -> None:
    result = match_recipe([], ["onion", "garlic"], _NO_SUBS, _NO_SYNONYMS)

    assert result.match_score == 0.0
    assert result.can_cook is False
    assert result.matched_items == []
    assert result.missing_items == []


def test_substitution_weight_applied_in_scoring() -> None:
    # 2 ingredients: 1 exact match (weight 1.0), 1 substitutable
    # (weight settings.substitution_match_weight = 0.7).
    # base = (1.0 + 0.7) / 2 = 0.85.
    substitution_map = {
        "butter": [SubstitutionOption(substitute="olive oil", ratio="3:4", flavor_impact="noticeable")]
    }
    recipe = [_ingredient("onion", "important"), _ingredient("butter", "important")]
    pantry = ["onion", "olive oil"]

    result = match_recipe(recipe, pantry, substitution_map, _NO_SYNONYMS)

    assert result.match_score == round((1.0 + settings.substitution_match_weight) / 2, 4)
    assert len(result.substitutable_items) == 1
    assert result.substitutable_items[0].substitute == "olive oil"
    assert result.substitutable_items[0].original == "butter"


def test_prefers_minimal_flavor_impact_substitute_over_others() -> None:
    substitution_map = {
        "butter": [
            SubstitutionOption(substitute="margarine", ratio="1:1", flavor_impact="significant"),
            SubstitutionOption(substitute="applesauce", ratio="1:1", flavor_impact="noticeable"),
            SubstitutionOption(substitute="vegan margarine", ratio="1:1", flavor_impact="minimal"),
        ]
    }
    recipe = [_ingredient("butter", "important")]
    pantry = ["margarine", "applesauce", "vegan margarine"]

    result = match_recipe(recipe, pantry, substitution_map, _NO_SYNONYMS)

    assert result.substitutable_items[0].substitute == "vegan margarine"


def test_dairy_substitute_rejected_under_dairy_free_constraint() -> None:
    substitution_map = {
        "milk": [SubstitutionOption(substitute="heavy cream", ratio="1:1", flavor_impact="minimal")]
    }
    recipe = [_ingredient("milk", "important")]
    pantry = ["heavy cream"]

    unrestricted = match_recipe(recipe, pantry, substitution_map, _NO_SYNONYMS)
    assert len(unrestricted.substitutable_items) == 1
    assert unrestricted.substitutable_items[0].substitute == "heavy cream"

    restricted = match_recipe(
        recipe, pantry, substitution_map, _NO_SYNONYMS, dietary_restrictions=["dairy_free"]
    )
    assert restricted.substitutable_items == []
    assert len(restricted.missing_items) == 1
    assert restricted.missing_items[0].name == "milk"


def test_dairy_free_substitute_accepted_without_the_constraint() -> None:
    substitution_map = {
        "butter": [SubstitutionOption(substitute="olive oil", ratio="3:4", flavor_impact="noticeable")]
    }
    recipe = [_ingredient("butter", "important")]
    pantry = ["olive oil"]

    result = match_recipe(
        recipe, pantry, substitution_map, _NO_SYNONYMS, dietary_restrictions=["dairy_free"]
    )

    assert len(result.substitutable_items) == 1
    assert result.substitutable_items[0].substitute == "olive oil"


def test_substitute_must_actually_be_available_in_pantry() -> None:
    substitution_map = {
        "butter": [SubstitutionOption(substitute="olive oil", ratio="3:4", flavor_impact="noticeable")]
    }
    recipe = [_ingredient("butter", "important")]
    pantry: list[str] = []  # olive oil not actually on hand

    result = match_recipe(recipe, pantry, substitution_map, _NO_SYNONYMS)

    assert result.substitutable_items == []
    assert len(result.missing_items) == 1
    assert result.missing_items[0].name == "butter"


def test_synonym_resolution_used_for_both_pantry_and_recipe_side() -> None:
    synonym_map = {"capsicum": "bell pepper"}
    recipe = [_ingredient("bell pepper", "important")]
    pantry = ["capsicum"]

    result = match_recipe(recipe, pantry, _NO_SUBS, synonym_map)

    assert len(result.matched_items) == 1
    assert result.matched_items[0].name == "bell pepper"
