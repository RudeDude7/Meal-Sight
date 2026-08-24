"""Tests for mealsight.perception.processor.analyze_voice_memo, with
FakeAudioProvider/FakeTextProvider standing in for the real Groq/
Mistral calls — no live API call anywhere in this file."""

from __future__ import annotations

import pytest

from mealsight.perception.models import RawExtractedConstraints
from mealsight.perception.processor import analyze_voice_memo
from mealsight.providers.exceptions import InvalidResponse, ProviderUnavailable
from tests.test_perception.conftest import FakeAudioProvider, FakeTextProvider, make_wav_bytes

_SYNONYMS = {"scallion": "green onion"}


def _patch_providers(
    monkeypatch: pytest.MonkeyPatch, audio: FakeAudioProvider, text: FakeTextProvider
) -> None:
    monkeypatch.setattr("mealsight.perception.processor.get_audio_provider", lambda: audio)
    monkeypatch.setattr("mealsight.perception.processor.get_text_provider", lambda: text)


async def test_transcript_parses_into_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = FakeAudioProvider(text="Cooking for four, forty five minutes, no peanuts.")
    text = FakeTextProvider(
        result=RawExtractedConstraints(
            servings=4,
            max_cook_time_minutes=45,
            avoid_ingredients=["peanuts"],
            dietary_restrictions=["peanut-free"],
        )
    )
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map={})

    assert len(audio.calls) == 1
    assert len(text.calls) == 1
    assert result.raw_transcript == "Cooking for four, forty five minutes, no peanuts."
    assert result.servings == 4
    assert result.max_cook_time_minutes == 45
    assert result.avoid_ingredients == ["peanut"]  # normalize_ingredient singularizes "peanuts"
    assert result.dietary_restrictions == ["peanut-free"]


async def test_self_correction_takes_the_final_value(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = FakeAudioProvider(text="Make it for two — actually, three.")
    # Simulating what a correctly-following extraction model would
    # return for this transcript: the FakeTextProvider doesn't run real
    # extraction, so this test asserts the pipeline passes the model's
    # own final-value answer straight through, not that the model always
    # gets it right — the real extraction quality is what verification
    # step 2/3 (live API, scored against voice_scripts.json) checks.
    text = FakeTextProvider(result=RawExtractedConstraints(servings=3))
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map={})

    assert result.servings == 3


async def test_unstated_fields_are_null_not_invented(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = FakeAudioProvider(text="Something quick-ish, nothing crazy.")
    text = FakeTextProvider(result=RawExtractedConstraints())
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map={})

    assert result.servings is None
    assert result.max_cook_time_minutes is None
    assert result.cuisine_preference is None
    assert result.protein_preference is None
    assert result.occasion is None
    assert result.dietary_restrictions == []
    assert result.avoid_ingredients == []
    assert result.avoid_dishes == []


async def test_loose_dietary_phrasing_normalizes_to_the_fixed_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = FakeAudioProvider(text="No dairy please, and keep it gluten free too.")
    text = FakeTextProvider(
        result=RawExtractedConstraints(dietary_restrictions=["no dairy", "gluten free"])
    )
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map={})

    assert set(result.dietary_restrictions) == {"dairy-free", "gluten-free"}


async def test_unrecognized_dietary_phrase_is_dropped_but_preserved_in_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = FakeAudioProvider(text="Keep it low glycemic please.")
    text = FakeTextProvider(result=RawExtractedConstraints(dietary_restrictions=["low glycemic"]))
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map={})

    assert result.dietary_restrictions == []
    assert result.additional_context is not None
    assert "low glycemic" in result.additional_context


async def test_avoid_ingredients_canonicalize(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = FakeAudioProvider(text="No scallions please.")
    text = FakeTextProvider(result=RawExtractedConstraints(avoid_ingredients=["scallions"]))
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map=_SYNONYMS)

    assert result.avoid_ingredients == ["green onion"]


async def test_oversized_audio_rejected_before_any_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mealsight.perception.validation.MAX_AUDIO_FILE_SIZE_MB", 0.0001)
    audio = FakeAudioProvider(text="unused")
    text = FakeTextProvider(result=RawExtractedConstraints())
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map={})

    assert audio.calls == []
    assert text.calls == []
    assert result.raw_transcript == ""
    assert result.additional_context is not None


async def test_wrong_format_rejected_before_any_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = FakeAudioProvider(text="unused")
    text = FakeTextProvider(result=RawExtractedConstraints())
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(b"not audio at all", synonym_map={})

    assert audio.calls == []
    assert text.calls == []
    assert result.raw_transcript == ""


async def test_transcription_failure_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = FakeAudioProvider(
        error=ProviderUnavailable("simulated outage", provider="groq", model_id="test-model")
    )
    text = FakeTextProvider(result=RawExtractedConstraints())
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map={})

    assert result.raw_transcript == ""
    assert result.servings is None
    assert text.calls == []
    assert result.additional_context is not None
    assert "unavailable" in result.additional_context.lower()


async def test_extraction_failure_preserves_the_transcript_with_empty_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio = FakeAudioProvider(text="A real transcript that was successfully captured.")
    text = FakeTextProvider(
        error=InvalidResponse(
            "simulated bad extraction", provider="mistral", model_id="test-model", raw_text="garbage"
        )
    )
    _patch_providers(monkeypatch, audio, text)

    result = await analyze_voice_memo(make_wav_bytes(), synonym_map={})

    assert result.raw_transcript == "A real transcript that was successfully captured."
    assert result.servings is None
    assert result.dietary_restrictions == []
    assert result.additional_context is not None
    assert "unavailable" in result.additional_context.lower()
