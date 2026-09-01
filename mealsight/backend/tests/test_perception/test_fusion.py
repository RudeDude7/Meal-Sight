"""Tests for mealsight.perception.fusion.merge_perceptions — pure,
synchronous, no providers or database involved at all."""

from __future__ import annotations

import pytest

from mealsight.perception.fusion import merge_perceptions
from mealsight.perception.models import AudioPerception, IdentifiedItem, TextPerception, VisionPerception
from mealsight.user_intelligence.models import UserProfile


def _vision(items: list[IdentifiedItem] | None = None) -> VisionPerception:
    return VisionPerception(
        identified_items=items or [], total_items_found=len(items or []), photo_quality="clear", notes=None
    )


def _item(
    name: str,
    category: str = "vegetable",
    freshness: str | None = "fresh",
    quantity: float | None = 1.0,
) -> IdentifiedItem:
    return IdentifiedItem(
        name=name, quantity=quantity, unit="count", category=category, freshness=freshness, confidence="high"
    )


def _audio(**kwargs: object) -> AudioPerception:
    base: dict[str, object] = {
        "raw_transcript": "test transcript",
        "servings": None,
        "max_cook_time_minutes": None,
        "dietary_restrictions": [],
        "cuisine_preference": None,
        "avoid_ingredients": [],
        "avoid_dishes": [],
        "mood_or_preference": None,
        "protein_preference": None,
        "occasion": None,
        "additional_context": None,
    }
    base.update(kwargs)
    return AudioPerception(**base)  # type: ignore[arg-type]


def _text(**kwargs: object) -> TextPerception:
    base: dict[str, object] = {
        "servings": None,
        "max_cook_time_minutes": None,
        "dietary_restrictions": [],
        "cuisine_preference": None,
        "avoid_ingredients": [],
        "avoid_dishes": [],
        "mood_or_preference": None,
        "protein_preference": None,
        "occasion": None,
        "additional_context": None,
    }
    base.update(kwargs)
    return TextPerception(**base)  # type: ignore[arg-type]


def test_zero_modalities_is_an_error() -> None:
    with pytest.raises(ValueError, match="at least one modality"):
        merge_perceptions(None, None, None)


def test_vision_only_works() -> None:
    result = merge_perceptions(_vision([_item("onion")]), None, None)
    assert result.modalities_received == ["vision"]
    assert [i.name for i in result.available_ingredients] == ["onion"]


def test_audio_only_works() -> None:
    result = merge_perceptions(None, _audio(servings=2), None)
    assert result.modalities_received == ["audio"]
    assert result.servings == 2


def test_text_only_works() -> None:
    result = merge_perceptions(None, None, _text(servings=3))
    assert result.modalities_received == ["text"]
    assert result.servings == 3


def test_conflicting_cook_times_take_the_lower_and_record_the_conflict() -> None:
    result = merge_perceptions(
        None, _audio(max_cook_time_minutes=45), _text(max_cook_time_minutes=20)
    )

    assert result.max_cook_time_minutes == 20
    assert len(result.conflicts_detected) == 1
    conflict = result.conflicts_detected[0]
    assert conflict.field == "max_cook_time_minutes"
    assert conflict.audio_value == 45
    assert conflict.text_value == 20
    assert conflict.chosen_value == 20


def test_conflicting_servings_take_the_lower_and_record_the_conflict() -> None:
    result = merge_perceptions(None, _audio(servings=4), _text(servings=2))

    assert result.servings == 2
    assert any(c.field == "servings" and c.chosen_value == 2 for c in result.conflicts_detected)


def test_agreeing_scalar_field_produces_no_conflict() -> None:
    result = merge_perceptions(None, _audio(max_cook_time_minutes=30), _text(max_cook_time_minutes=30))

    assert result.max_cook_time_minutes == 30
    assert result.conflicts_detected == []


def test_conflicting_cuisine_prefers_text_and_records_it() -> None:
    result = merge_perceptions(
        None, _audio(cuisine_preference="Mexican"), _text(cuisine_preference="Thai")
    )

    assert result.cuisine_preference == "Thai"
    assert len(result.conflicts_detected) == 1
    conflict = result.conflicts_detected[0]
    assert conflict.field == "cuisine_preference"
    assert conflict.chosen_value == "Thai"
    assert conflict.audio_value == "Mexican"
    assert conflict.text_value == "Thai"


def test_audio_mentioned_ingredient_absent_from_photo_is_flagged_unverified() -> None:
    result = merge_perceptions(
        _vision([_item("onion")]), _audio(protein_preference="salmon"), None
    )

    unverified = [i for i in result.available_ingredients if not i.verified]
    assert len(unverified) == 1
    assert unverified[0].name == "salmon"
    assert unverified[0].source == "audio"
    assert unverified[0].note is not None
    assert "off-camera" in unverified[0].note


def test_protein_preference_already_seen_in_photo_is_not_duplicated() -> None:
    result = merge_perceptions(
        _vision([_item("chicken", category="protein")]), _audio(protein_preference="chicken"), None
    )

    matching = [i for i in result.available_ingredients if i.name == "chicken"]
    assert len(matching) == 1
    assert matching[0].verified is True


def test_dietary_restrictions_union_across_audio_and_text() -> None:
    result = merge_perceptions(
        None,
        _audio(dietary_restrictions=["dairy-free"]),
        _text(dietary_restrictions=["gluten-free"]),
    )

    assert set(result.dietary_restrictions) == {"dairy-free", "gluten-free"}


def test_profile_defaults_apply_only_when_unspecified() -> None:
    profile = UserProfile(
        dietary_restrictions=[],
        disliked_ingredients=[],
        preferred_cook_time_minutes=25,
        household_size=2,
        protein_preference=None,
        cooking_skill="intermediate",
        budget_sensitivity="moderate",
        cuisine_preferences={},
        cuisine_preference_data_points={},
    )

    # Unspecified — profile fills in.
    result = merge_perceptions(None, _audio(), None, user_profile=profile)
    assert result.servings == 2
    assert result.max_cook_time_minutes == 25

    # Specified — profile does NOT override.
    result_specified = merge_perceptions(
        None, _audio(servings=6, max_cook_time_minutes=10), None, user_profile=profile
    )
    assert result_specified.servings == 6
    assert result_specified.max_cook_time_minutes == 10


def test_dairy_item_survives_a_dairy_free_constraint_with_a_note() -> None:
    result = merge_perceptions(
        _vision([_item("milk", category="dairy")]), _audio(dietary_restrictions=["dairy-free"]), None
    )

    milk = next(i for i in result.available_ingredients if i.name == "milk")
    assert milk.verified is True
    assert "dairy-free" in (milk.note or "")
    assert [i.name for i in result.available_ingredients] == ["milk"]  # never removed


def test_freshness_alert_for_non_fresh_item() -> None:
    result = merge_perceptions(_vision([_item("spinach", freshness="wilted")]), None, None)

    assert len(result.freshness_alerts) == 1
    assert result.freshness_alerts[0].name == "spinach"
    assert result.freshness_alerts[0].freshness == "wilted"


def test_fresh_item_produces_no_freshness_alert() -> None:
    result = merge_perceptions(_vision([_item("onion", freshness="fresh")]), None, None)
    assert result.freshness_alerts == []
