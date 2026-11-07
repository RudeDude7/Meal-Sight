"""The demo pantry fixture and the scorecard's description of it."""

from __future__ import annotations

from eval.runner import DEMO_PANTRY_FIXTURE, describe_pantry_fixture
from mealsight.pantry.models import PantryItemInput


def test_fixture_items_are_valid_pantry_inputs() -> None:
    import json

    fixture = json.loads(DEMO_PANTRY_FIXTURE.read_text())
    groups = [*fixture["photos"].values(), fixture["staples"]]
    items = [PantryItemInput(**raw) for group in groups for raw in group]
    assert len(items) > 50


def test_scorecard_description_names_every_staple_and_photo() -> None:
    description = describe_pantry_fixture()
    assert {"olive oil", "salt", "black pepper", "all purpose flour", "sugar"} <= set(
        description["staples_added_by_hand"]
    )
    assert description["photo_sources"] and all(count > 0 for count in description["photo_sources"].values())
    assert "eggs" in description["staples_note"]  # states what was deliberately NOT seeded
