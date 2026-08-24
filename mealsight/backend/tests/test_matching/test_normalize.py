"""Tests for mealsight.matching.normalize.normalize_ingredient."""

from __future__ import annotations

import pytest

from mealsight.matching.normalize import normalize_ingredient

# Every one of these must survive as its own, distinct multi-word
# ingredient — none may collapse down to just one of its own words.
PROTECTED_CASES = [
    ("Sweet Potato", "sweet potato"),
    ("sweet potatoes", "sweet potato"),
    ("Cream Cheese", "cream cheese"),
    ("Green Onion", "green onion"),
    ("green onions", "green onion"),
    ("Sour Cream", "sour cream"),
    ("Coconut Milk", "coconut milk"),
    ("Peanut Butter", "peanut butter"),
    ("Chicken Stock", "chicken stock"),
    ("Brown Sugar", "brown sugar"),
    ("Rice Flour", "rice flour"),
    ("Corn Flour", "corn flour"),
    ("Soy Sauce", "soy sauce"),
]


@pytest.mark.parametrize(("raw", "expected"), PROTECTED_CASES)
def test_protected_terms_survive_intact(raw: str, expected: str) -> None:
    assert normalize_ingredient(raw) == expected


@pytest.mark.parametrize(
    ("protected_raw", "bare_raw"),
    [
        ("Sweet Potato", "Potato"),
        ("Cream Cheese", "Cream"),
        ("Green Onion", "Onion"),
        ("Sour Cream", "Cream"),
        ("Peanut Butter", "Butter"),
        ("Chicken Stock", "Chicken"),
        ("Brown Sugar", "Sugar"),
    ],
)
def test_protected_terms_never_collapse_to_their_bare_component(protected_raw: str, bare_raw: str) -> None:
    assert normalize_ingredient(protected_raw) != normalize_ingredient(bare_raw)


def test_lowercases_and_strips_punctuation() -> None:
    assert normalize_ingredient("Garlic, minced!") == "garlic"


def test_strips_container_words() -> None:
    assert normalize_ingredient("a can of chopped tomatoes") == "tomato"
    assert normalize_ingredient("a jar of peanut butter") == "peanut butter"


def test_strips_prep_modifiers_but_keeps_identity() -> None:
    assert normalize_ingredient("Chopped onion") == "onion"
    assert normalize_ingredient("Freshly chopped parsley") == "parsley"
    assert normalize_ingredient("Cubed Feta cheese") == "feta cheese"
    assert normalize_ingredient("Minced garlic") == "garlic"
    assert normalize_ingredient("boneless skinless chicken breast") == "chicken breast"


def test_singularizes_plurals() -> None:
    assert normalize_ingredient("eggs") == "egg"
    assert normalize_ingredient("tomatoes") == "tomato"
    assert normalize_ingredient("onions") == "onion"
    assert normalize_ingredient("berries") == "berry"


def test_uncountable_words_are_not_mangled() -> None:
    assert normalize_ingredient("Hummus") == "hummus"
    assert normalize_ingredient("Couscous") == "couscous"


def test_empty_and_none_like_input() -> None:
    assert normalize_ingredient("") == ""


def test_real_seeded_ingredient_text() -> None:
    # Pulled directly from the real seeded recipes.db (Garides Saganaki).
    assert normalize_ingredient("Raw king prawns") == "king prawn"
    assert normalize_ingredient("Chopped tomatoes") == "tomato"
