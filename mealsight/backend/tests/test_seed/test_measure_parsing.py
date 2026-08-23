"""Tests for mealsight.seed.recipe_parsing.parse_measure and split_steps."""

from __future__ import annotations

import pytest

from mealsight.seed.recipe_parsing import parse_measure, split_steps


@pytest.mark.parametrize(
    ("raw", "expected_quantity", "expected_unit"),
    [
        ("1 tbsp", 1.0, "tbsp"),
        ("2 tablespoons", 2.0, "tbsp"),
        ("1/2 cup", 0.5, "cup"),
        ("3/4 tsp", 0.75, "tsp"),
        ("400g", 400.0, "g"),
        ("1kg", 1.0, "kg"),
        ("1 clove", 1.0, "clove"),
    ],
)
def test_parse_measure_plain_fractions_and_units(
    raw: str, expected_quantity: float, expected_unit: str
) -> None:
    quantity, unit = parse_measure(raw)
    assert quantity == pytest.approx(expected_quantity)
    assert unit == expected_unit


@pytest.mark.parametrize(
    ("raw", "expected_quantity"),
    [
        ("½ cup", 0.5),
        ("¼ tsp", 0.25),
        ("¾ cup", 0.75),
        ("1 ½ cups", 1.5),
        ("2¼ cups", 2.25),
    ],
)
def test_parse_measure_unicode_fractions(raw: str, expected_quantity: float) -> None:
    quantity, _unit = parse_measure(raw)
    assert quantity == pytest.approx(expected_quantity)


@pytest.mark.parametrize(
    ("raw", "expected_midpoint"),
    [
        ("2-3 tomatoes", 2.5),
        ("2 to 3 cloves", 2.5),
        ("1-2 tbsp", 1.5),
    ],
)
def test_parse_measure_ranges_take_midpoint(raw: str, expected_midpoint: float) -> None:
    quantity, _unit = parse_measure(raw)
    assert quantity == pytest.approx(expected_midpoint)


@pytest.mark.parametrize(
    "raw",
    ["2", "1 large", "3 chopped", "Salt and pepper"],
)
def test_parse_measure_missing_or_unrecognized_unit_is_none(raw: str) -> None:
    _quantity, unit = parse_measure(raw)
    assert unit is None


def test_parse_measure_dash_has_no_quantity_but_keeps_unit() -> None:
    quantity, unit = parse_measure("Dash")
    assert quantity is None
    assert unit == "dash"


def test_parse_measure_pinch_has_no_quantity_but_keeps_unit() -> None:
    quantity, unit = parse_measure("Pinch")
    assert quantity is None
    assert unit == "pinch"


@pytest.mark.parametrize("raw", ["To taste", "to taste", "", None])
def test_parse_measure_non_numeric_measures_are_fully_empty(raw: str | None) -> None:
    quantity, unit = parse_measure(raw)
    assert quantity is None
    assert unit is None


def test_split_steps_strips_step_prefixes() -> None:
    raw = "step 1\r\nDo the first thing.\r\n\r\nstep 2\r\nDo the second thing."
    assert split_steps(raw) == ["Do the first thing.", "Do the second thing."]


def test_split_steps_handles_plain_paragraphs_with_no_step_markers() -> None:
    raw = "Preheat the oven.\r\nMix the batter.\r\nBake for 20 minutes."
    assert split_steps(raw) == ["Preheat the oven.", "Mix the batter.", "Bake for 20 minutes."]
