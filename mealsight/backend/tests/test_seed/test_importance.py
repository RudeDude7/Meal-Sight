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


def test_term_match_is_whole_word_not_raw_substring() -> None:
    # Real bug found in Phase 2.2 verification: "egg" (a PROTEIN_TERMS
    # entry) matched as a raw substring inside "Parmigiano-Reggiano"
    # ("reggiano" contains "egg"), wrongly making a cheese garnish the
    # recipe's one critical ingredient in a dish with no actual egg.
    result = assign_importances(
        "Spicy Arrabiata Penne",
        ["Penne Rigate", "Olive Oil", "Garlic", "Chopped Tomatoes", "Basil", "Parmigiano-Reggiano"],
    )
    assert result[5] != "critical"


def test_protein_ingredient_is_not_downgraded_to_optional_by_a_seasoning_word_prefix() -> None:
    # "Salt Cod" contains the genuine whole word "salt" (a seasoning
    # term), but it's a defining protein ingredient, not a seasoning —
    # a real protein match must win over an incidental seasoning-word
    # collision.
    result = assign_importances("Saltfish and Ackee", ["Salt Cod", "Ackee", "Onion"])
    assert result[0] == "important"


def test_defining_staple_reaches_critical_when_title_names_no_ingredient() -> None:
    # KNOWN_ISSUES.md #2's own real example, reproduced directly:
    # "Spanish Tortilla" names no ingredient in its English title at
    # all, and potato is not a PROTEIN_TERMS entry — before the fix this
    # recipe reached zero critical ingredients.
    result = assign_importances("Spanish Tortilla", ["Potatoes", "Eggs", "Onion", "Olive Oil"])
    assert result[0] == "critical"
    assert result.count("critical") == 1


def test_defining_staple_beats_a_minor_background_protein_ingredient() -> None:
    # The failure mode the investigation actually found in the real
    # corpus (Pierogi, Rappie Pie): a defining staple sitting LATER in
    # the ingredient list than a minor protein-term match (egg in the
    # dough, a splash of stock) must still win — the staple tier is
    # checked BEFORE the protein-term fallback, not after it.
    result = assign_importances(
        "Rappie Pie", ["Chicken Stock", "Onion", "Potatoes", "Butter"]
    )
    assert result[2] == "critical"
    assert result.count("critical") == 1


def test_defining_staple_tier_never_overrides_a_real_title_match() -> None:
    # Title-match (tier 1) still wins outright when the title genuinely
    # names an ingredient — the new staple tier only ever fires when
    # tier 1 finds nothing at all.
    result = assign_importances("Chicken Couscous", ["Couscous", "Chicken", "Lemon"])
    assert result[0] == "critical"
    assert result.count("critical") == 1


def test_defining_staple_tier_never_overrides_a_title_named_protein() -> None:
    # A dual-defining dish where the title itself names a protein
    # (salmon) must still resolve via title-match, not the new staple
    # tier — the real corpus's own Salmon Prawn Risotto case.
    result = assign_importances("Salmon Prawn Risotto", ["Rice", "Salmon", "Prawns", "Butter"])
    assert result[1] == "critical"
    assert result.count("critical") == 1


def test_pasta_shape_name_reaches_critical_even_without_the_word_pasta() -> None:
    # Fettucine alfredo's real ingredient is literally named
    # "Fettuccine" — it never contains the substring "pasta" at all, so
    # a generic "pasta" term alone would still miss it.
    result = assign_importances("Fettucine alfredo", ["Butter", "Parmesan Cheese", "Fettuccine"])
    assert result[2] == "critical"
