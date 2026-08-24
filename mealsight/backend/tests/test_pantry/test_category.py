"""Tests for mealsight.pantry.category.resolve_category."""

from __future__ import annotations

from mealsight.pantry.category import resolve_category
from mealsight.pantry.shelf_life import ShelfLifeEntry

_EMPTY_MAP: dict[str, ShelfLifeEntry] = {}


def test_exact_shelf_life_row_wins_over_everything_else() -> None:
    # "onion" would otherwise match the vegetable keyword rule — but an
    # exact reference row (even a deliberately wrong category, to prove
    # priority) must win.
    shelf_life_map = {"onion": ShelfLifeEntry("condiment", 30, None, 30)}
    assert resolve_category("onion", shelf_life_map) == "condiment"


def test_explicit_map_used_when_no_shelf_life_row_exists() -> None:
    assert resolve_category("water", _EMPTY_MAP) == "other"
    assert resolve_category("corn", _EMPTY_MAP) == "vegetable"


def test_keyword_rule_reuses_recipe_parsing_protein_terms() -> None:
    assert resolve_category("chicken breast", _EMPTY_MAP) == "protein"
    assert resolve_category("prawn", _EMPTY_MAP) == "protein"


def test_keyword_rule_reuses_recipe_parsing_dairy_terms() -> None:
    assert resolve_category("cheddar", _EMPTY_MAP) == "dairy"


def test_vegetable_keyword_rule() -> None:
    assert resolve_category("red onion", _EMPTY_MAP) == "vegetable"


def test_fruit_keyword_rule() -> None:
    assert resolve_category("granny smith apple", _EMPTY_MAP) == "fruit"


def test_grain_keyword_rule() -> None:
    assert resolve_category("penne pasta", _EMPTY_MAP) == "grain"


def test_condiment_keyword_rule() -> None:
    assert resolve_category("barbecue sauce", _EMPTY_MAP) == "condiment"


def test_spice_keyword_rule() -> None:
    assert resolve_category("ground cinnamon", _EMPTY_MAP) == "spice"


def test_whole_word_matching_not_substring() -> None:
    # "cheesecake" contains the substring "cheese" but is not, itself,
    # cheese — the same discipline recipe_parsing._matches_any_term_
    # whole_word exists to enforce (its own docstring cites the "egg"
    # inside "reggiano" bug this class of check avoids).
    assert resolve_category("cheesecake", _EMPTY_MAP) != "dairy"


def test_unrecognized_item_falls_back_to_other() -> None:
    assert resolve_category("completely unheard of substance", _EMPTY_MAP) == "other"
