"""Tests for mealsight.matching.specificity: asymmetric specificity
matching between a recipe requirement and a pantry item."""

from __future__ import annotations

import pytest

from mealsight.matching.matcher import RecipeIngredientInput, match_recipe
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.specificity import compare_specificity
from mealsight.matching.substitutions import SubstitutionOption

_NO_SUBS: dict[str, list[SubstitutionOption]] = {}
_NO_SYNONYMS: dict[str, str] = {}


@pytest.mark.parametrize(
    ("recipe_raw", "pantry_raw", "expected"),
    [
        ("chicken", "chicken thighs", "full"),
        ("chicken thighs", "chicken", "partial"),
        ("sweet potato", "potato", "none"),
        ("potato", "sweet potato", "none"),
        ("beef", "ground beef", "full"),
        ("milk", "coconut milk", "none"),
        ("onion", "red onion", "full"),
        ("onion", "green onion", "none"),
        ("salmon", "salmon fillet", "full"),
        ("chicken", "chicken breast", "full"),
        ("chicken breast", "chicken", "partial"),
    ],
)
def test_compare_specificity(recipe_raw: str, pantry_raw: str, expected: str) -> None:
    recipe_normalized = normalize_ingredient(recipe_raw)
    pantry_normalized = normalize_ingredient(pantry_raw)
    assert compare_specificity(recipe_normalized, pantry_normalized) == expected


def test_chicken_thighs_in_pantry_fully_satisfies_recipe_requiring_chicken() -> None:
    recipe = [RecipeIngredientInput(name="chicken", importance="critical")]
    pantry = ["chicken thighs"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert len(result.matched_items) == 1
    assert result.partial_matches == []
    assert result.critical_missing == []
    assert result.match_score == 1.0
    assert result.can_cook is True


def test_generic_chicken_in_pantry_only_partially_satisfies_recipe_requiring_chicken_thighs() -> None:
    recipe = [RecipeIngredientInput(name="chicken thighs", importance="important")]
    pantry = ["chicken"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert result.matched_items == []
    assert result.missing_items == []
    assert len(result.partial_matches) == 1
    assert result.partial_matches[0].pantry_match == "chicken"
    assert result.partial_matches[0].name == "chicken thigh"


def test_sweet_potato_does_not_satisfy_plain_potato_requirement() -> None:
    recipe = [RecipeIngredientInput(name="potato", importance="critical")]
    pantry = ["sweet potato"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert result.matched_items == []
    assert result.partial_matches == []
    assert result.critical_missing == ["potato"]


def test_plain_potato_does_not_satisfy_sweet_potato_requirement() -> None:
    recipe = [RecipeIngredientInput(name="sweet potato", importance="critical")]
    pantry = ["potato"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert result.matched_items == []
    assert result.partial_matches == []
    assert result.critical_missing == ["sweet potato"]


def test_green_onion_does_not_satisfy_plain_onion_requirement() -> None:
    recipe = [RecipeIngredientInput(name="onion", importance="important")]
    pantry = ["green onion"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert result.matched_items == []
    assert result.partial_matches == []
    assert len(result.missing_items) == 1


def test_red_onion_satisfies_plain_onion_requirement() -> None:
    recipe = [RecipeIngredientInput(name="onion", importance="important")]
    pantry = ["red onion"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert len(result.matched_items) == 1
    assert result.missing_items == []


def test_coconut_milk_does_not_satisfy_plain_milk_requirement() -> None:
    recipe = [RecipeIngredientInput(name="milk", importance="important")]
    pantry = ["coconut milk"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert result.matched_items == []
    assert result.partial_matches == []
    assert len(result.missing_items) == 1


def test_partial_match_scored_at_substitution_weight() -> None:
    from mealsight.config.settings import settings

    recipe = [RecipeIngredientInput(name="chicken thighs", importance="important")]
    pantry = ["chicken"]

    result = match_recipe(recipe, pantry, _NO_SUBS, _NO_SYNONYMS)

    assert result.match_score == round(settings.substitution_match_weight, 4)
