"""Tests for mealsight.perception.validation.validate_audio."""

from __future__ import annotations

import pytest

from mealsight.config.settings import settings
from mealsight.perception.validation import AudioValidationError, validate_audio
from tests.test_perception.conftest import make_wav_bytes


def test_valid_wav_passes() -> None:
    validate_audio(make_wav_bytes(duration_seconds=2.0))


def test_oversized_audio_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mealsight.perception.validation.MAX_AUDIO_FILE_SIZE_MB", 0.0001)

    with pytest.raises(AudioValidationError, match="MB"):
        validate_audio(make_wav_bytes())


def test_wrong_format_is_rejected() -> None:
    with pytest.raises(AudioValidationError):
        validate_audio(b"this is not audio at all")


def test_too_long_duration_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_audio_duration_seconds", 1)

    with pytest.raises(AudioValidationError, match="limit"):
        validate_audio(make_wav_bytes(duration_seconds=5.0))


def test_webm_magic_bytes_are_recognized_as_a_valid_format() -> None:
    # A minimal, real EBML header — enough for detect_audio_format's own
    # magic-byte check to recognize it as WEBM; this pipeline
    # deliberately doesn't try to parse WEBM's duration (see
    # mealsight.perception.validation's own _WEBM_MAGIC comment), so a
    # bare header with no real Segment/Duration data still passes.
    webm_bytes = b"\x1a\x45\xdf\xa3" + b"\x00" * 20
    validate_audio(webm_bytes)
