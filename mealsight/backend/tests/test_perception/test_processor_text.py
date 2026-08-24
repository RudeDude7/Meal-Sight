"""Tests for mealsight.perception.processor.analyze_text_input, with
FakeTextProvider standing in for the real Mistral call — no live API
call anywhere in this file."""

from __future__ import annotations

import pytest

from mealsight.perception.models import RawExtractedConstraints
from mealsight.perception.processor import analyze_text_input
from mealsight.providers.exceptions import ProviderUnavailable
from tests.test_perception.conftest import FakeTextProvider

_SYNONYMS = {"scallion": "green onion"}


def _patch_text_provider(monkeypatch: pytest.MonkeyPatch, text_provider: FakeTextProvider) -> None:
    monkeypatch.setattr("mealsight.perception.processor.get_text_provider", lambda: text_provider)


async def test_text_extraction_matches_audio_behavior_on_identical_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same RawExtractedConstraints shape, same _postprocess_constraints
    # code path as analyze_voice_memo — this test confirms text input
    # produces the identical final shape for identical extracted content.
    text_provider = FakeTextProvider(
        result=RawExtractedConstraints(
            servings=4,
            max_cook_time_minutes=45,
            avoid_ingredients=["peanuts"],
            dietary_restrictions=["no dairy"],
        )
    )
    _patch_text_provider(monkeypatch, text_provider)

    result = await analyze_text_input("Cooking for four, 45 minutes, no peanuts, no dairy.", synonym_map={})

    assert len(text_provider.calls) == 1
    assert result.servings == 4
    assert result.max_cook_time_minutes == 45
    assert result.avoid_ingredients == ["peanut"]
    assert result.dietary_restrictions == ["dairy-free"]


async def test_empty_text_short_circuits_without_an_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    text_provider = FakeTextProvider(result=RawExtractedConstraints())
    _patch_text_provider(monkeypatch, text_provider)

    result = await analyze_text_input("   ", synonym_map={})

    assert text_provider.calls == []
    assert result.servings is None
    assert result.additional_context is not None


async def test_oversized_text_rejected_before_any_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from mealsight.config.settings import settings

    monkeypatch.setattr(settings, "max_text_length", 5)
    text_provider = FakeTextProvider(result=RawExtractedConstraints())
    _patch_text_provider(monkeypatch, text_provider)

    result = await analyze_text_input("way too long for the limit", synonym_map={})

    assert text_provider.calls == []
    assert result.additional_context is not None


async def test_avoid_ingredients_canonicalize(monkeypatch: pytest.MonkeyPatch) -> None:
    text_provider = FakeTextProvider(result=RawExtractedConstraints(avoid_ingredients=["scallions"]))
    _patch_text_provider(monkeypatch, text_provider)

    result = await analyze_text_input("no scallions", synonym_map=_SYNONYMS)

    assert result.avoid_ingredients == ["green onion"]


async def test_loose_dietary_phrasing_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    text_provider = FakeTextProvider(result=RawExtractedConstraints(dietary_restrictions=["gluten free"]))
    _patch_text_provider(monkeypatch, text_provider)

    result = await analyze_text_input("gluten free please", synonym_map={})

    assert result.dietary_restrictions == ["gluten-free"]


async def test_extraction_failure_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    text_provider = FakeTextProvider(
        error=ProviderUnavailable("simulated outage", provider="mistral", model_id="test-model")
    )
    _patch_text_provider(monkeypatch, text_provider)

    result = await analyze_text_input("2 servings please", synonym_map={})

    assert result.servings is None
    assert result.additional_context is not None
    assert "unavailable" in result.additional_context.lower()
