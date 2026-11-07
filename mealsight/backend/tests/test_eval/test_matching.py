"""Regression tests for eval.matching, the scorer ported from scripts/benchmark_vision.py."""

from __future__ import annotations

import pytest

from eval.matching import match_phrases, normalize_phrase


@pytest.mark.parametrize(
    ("predicted", "truth"),
    [
        ("potatoes (peeled)", "potato"),
        ('milk (carton labeled "Demi-Ecreme")', "milk"),
        ("sugar (in a jar)", "sugar"),
        ("Onions (in a container on the bottom shelf)", "onion"),
        ("potatoes (peeled and whole", "potato"),  # unclosed paren strips to end of string
    ],
)
def test_parenthetical_qualifiers_do_not_block_a_match(predicted: str, truth: str) -> None:
    assert match_phrases(predicted, truth)


def test_parenthetical_is_dropped_from_the_normalized_phrase() -> None:
    assert normalize_phrase("potatoes (peeled)") == "potato"


@pytest.mark.parametrize("predicted", ["Butter (Chavroux brand)", "butter (Chavroux)", "Chavroux"])
def test_brand_inside_parentheses_still_credits_the_brand_synonym(predicted: str) -> None:
    assert match_phrases(predicted, "goat cheese")


def test_stripping_parentheticals_does_not_merge_distinct_foods() -> None:
    assert not match_phrases("sweet potatoes (2)", "potato")
    assert not match_phrases("sugar substitute (Erycil)", "sugar")
