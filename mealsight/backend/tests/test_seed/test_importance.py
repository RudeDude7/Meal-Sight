"""Tests for mealsight.seed.recipe_parsing.assign_importances."""

from __future__ import annotations

from mealsight.seed.recipe_parsing import assign_importances


def test_importance_is_deterministic_across_repeated_runs() -> None:
    recipe_name = "Chicken Alfredo"
    ingredients = ["Chicken Breast", "Garlic", "Salt", "Parsley", "Heavy Cream"]

    first_run = assign_importances(recipe_name, ingredients)
    second_run = assign_importances(recipe_name, ingredients)
    third_run = assign_importances(recipe_name, ingredients)

    assert first_run == second_run == third_run


def test_ingredient_matching_recipe_name_is_critical() -> None:
    result = assign_importances("Chicken Alfredo", ["Chicken Breast", "Garlic", "Heavy Cream"])
    assert result[0] == "critical"


def test_protein_term_is_critical_when_nothing_matches_recipe_name() -> None:
    result = assign_importances("Weeknight Dinner", ["Onion", "Garlic", "Beef", "Salt"])
    assert result[2] == "critical"


def test_seasonings_and_garnishes_are_optional() -> None:
    result = assign_importances("Roast Chicken", ["Chicken", "Salt", "Parsley", "Black Pepper"])
    assert result[1] == "optional"
    assert result[2] == "optional"
    assert result[3] == "optional"


def test_aromatics_and_core_flavor_default_to_important() -> None:
    result = assign_importances("Weeknight Stew", ["Onion", "Garlic", "Soy Sauce"])
    assert result == ["important", "important", "important"]


def test_only_one_ingredient_is_ever_critical() -> None:
    result = assign_importances("Beef Stew", ["Beef", "Chicken Stock", "Carrots", "Onion"])
    assert result.count("critical") <= 1
