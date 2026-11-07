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
    result = merge_perceptions(None, _audio(max_cook_time_minutes=45), _text(max_cook_time_minutes=20))

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
    result = merge_perceptions(None, _audio(cuisine_preference="Mexican"), _text(cuisine_preference="Thai"))

    assert result.cuisine_preference == "Thai"
    assert len(result.conflicts_detected) == 1
    conflict = result.conflicts_detected[0]
    assert conflict.field == "cuisine_preference"
    assert conflict.chosen_value == "Thai"
    assert conflict.audio_value == "Mexican"
    assert conflict.text_value == "Thai"


def test_a_wanted_protein_is_not_added_as_an_ingredient_the_user_has() -> None:
    # "I want salmon" says nothing about salmon being on hand. Treating it as
    # an unverified pantry item made every salmon recipe look cookable.
    result = merge_perceptions(_vision([_item("onion")]), _audio(protein_preference="salmon"), None)

    assert [i.name for i in result.available_ingredients] == ["onion"]
    assert result.protein_preference == "salmon"


def test_a_stated_possession_reaches_matching_marked_unverified() -> None:
    result = merge_perceptions(_vision([_item("onion")]), _audio(ingredients_on_hand=["salmon"]), None)

    unverified = [i for i in result.available_ingredients if not i.verified]
    assert [i.name for i in unverified] == ["salmon"]
    assert unverified[0].source == "audio"
    assert unverified[0].note is not None
    assert "not seen in the photo" in unverified[0].note


def test_a_possession_stated_in_text_is_also_carried_and_not_duplicated_with_vision() -> None:
    result = merge_perceptions(
        _vision([_item("salmon", category="protein")]), None, _text(ingredients_on_hand=["salmon", "lemon"])
    )

    assert [i.name for i in result.available_ingredients] == ["salmon", "lemon"]
    assert [i.verified for i in result.available_ingredients] == [True, False]


def test_want_and_have_for_the_same_food_keep_both_meanings() -> None:
    result = merge_perceptions(None, None, _text(protein_preference="salmon", ingredients_on_hand=["salmon"]))

    assert result.protein_preference == "salmon"
    assert [i.name for i in result.available_ingredients] == ["salmon"]


def test_a_preference_alone_adds_nothing_even_alongside_a_stated_possession_of_something_else() -> None:
    result = merge_perceptions(None, None, _text(protein_preference="fish", ingredients_on_hand=["chicken"]))

    assert [i.name for i in result.available_ingredients] == ["chicken"]


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


def _saved(**kwargs: object) -> UserProfile:
    base: dict[str, object] = {
        "dietary_restrictions": [],
        "disliked_ingredients": [],
        "preferred_cook_time_minutes": 30,
        "household_size": 1,
        "protein_preference": None,
        "cooking_skill": "intermediate",
        "budget_sensitivity": "moderate",
        "cuisine_preferences": {},
        "cuisine_preference_data_points": {},
    }
    base.update(kwargs)
    return UserProfile(**base)  # type: ignore[arg-type]


def test_saved_dietary_restrictions_reach_the_request_as_if_stated() -> None:
    """Regression: a restriction saved on the profile (e.g. a nut allergy) was stored correctly and then
    never applied, because fusion read only servings and cook time from the profile."""
    profile = _saved(dietary_restrictions=["vegetarian", "nut_free", "Peanut Free"])
    result = merge_perceptions(None, None, _text(), user_profile=profile)
    assert result.dietary_restrictions == ["vegetarian", "nut-free", "peanut-free"]
    assert result.restrictions_from_profile == ["vegetarian", "nut-free", "peanut-free"]


def test_saved_and_stated_restrictions_are_a_union_without_duplicates() -> None:
    profile = _saved(dietary_restrictions=["vegetarian"])
    result = merge_perceptions(None, None, _text(dietary_restrictions=["gluten-free", "vegetarian"]), profile)
    assert result.dietary_restrictions == ["gluten-free", "vegetarian"]
    assert result.restrictions_from_profile == ["vegetarian"]


def test_an_unrecognized_saved_restriction_is_kept_to_be_disclosed_not_dropped() -> None:
    result = merge_perceptions(None, None, _text(), _saved(dietary_restrictions=["no pork"]))
    assert result.dietary_restrictions == ["no-pork"]
    assert result.unenforced_restrictions == ["no-pork"]


def test_a_saved_restriction_goes_through_the_same_split_as_a_stated_one() -> None:
    from mealsight.matching.diet import split_restrictions

    result = merge_perceptions(
        None, None, _text(), _saved(dietary_restrictions=["peanut-free", "vegan", "keto"])
    )
    split = split_restrictions(result.dietary_restrictions)
    assert (split.tag_filters, split.ingredient, split.unenforced) == (["vegan"], ["peanut-free"], ["keto"])


def test_no_profile_and_an_empty_profile_add_no_restrictions() -> None:
    assert merge_perceptions(None, None, _text(), None).dietary_restrictions == []
    assert merge_perceptions(None, None, _text(), _saved()).restrictions_from_profile == []


def test_saved_protein_preference_is_a_default_that_a_stated_one_overrides() -> None:
    profile = _saved(protein_preference="chicken")
    defaulted = merge_perceptions(None, None, _text(), profile)
    assert defaulted.protein_preference == "chicken" and defaulted.protein_preference_is_default is True
    stated = merge_perceptions(None, None, _text(protein_preference="salmon"), profile)
    assert stated.protein_preference == "salmon" and stated.protein_preference_is_default is False
    assert merge_perceptions(None, None, _text(), _saved()).protein_preference is None
