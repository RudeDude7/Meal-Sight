"""Fixtures for mealsight.perception tests: a fresh pantry.db Database
per test, real (Pillow/wave-generated) minimal media for validation
tests to decode, and Fake providers standing in for the real Mistral/
Groq calls — no live API call anywhere in this test package.
"""

from __future__ import annotations

import wave
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import TypeVar

import pytest
from PIL import Image
from pydantic import BaseModel

from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database
from mealsight.pantry.shelf_life import reset_shelf_life_cache
from mealsight.providers.base import TextResponse, TranscriptionResponse

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    reset_shelf_life_cache()


@pytest.fixture
async def pantry_db(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(tmp_path / "pantry_test.db", name="pantry", schema_path=SCHEMA_DIR / "pantry.sql")
    await init_database(db, db.schema_path)
    yield db
    await db.close()


class FakeVisionProvider:
    """Stands in for the real Mistral vision provider: analyze_image
    returns a pre-baked TextResponse, or raises a pre-baked exception —
    never makes a network call. Records every call it receives so a
    test can assert whether the provider was ever actually reached."""

    def __init__(self, text: str | None = None, error: BaseException | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[tuple[bytes, str, str]] = []

    async def analyze_image(
        self, image_bytes: bytes, prompt: str, model_id: str, *, system: str | None = None
    ) -> TextResponse:
        self.calls.append((image_bytes, prompt, model_id))
        if self._error is not None:
            raise self._error
        assert self._text is not None
        return TextResponse(
            text=self._text,
            model_id=model_id,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
        )


def make_jpeg_bytes(width: int = 400, height: int = 400) -> bytes:
    """A real, minimal, valid JPEG, built with Pillow — so validate_
    image's own Pillow-based decode step actually succeeds against it,
    rather than a hand-rolled byte stub that only looks like an image."""
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(200, 200, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def make_webp_bytes(width: int = 400, height: int = 400) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(200, 200, 200)).save(buffer, format="WEBP")
    return buffer.getvalue()


def make_wav_bytes(duration_seconds: float = 2.0, frame_rate: int = 16000) -> bytes:
    """A real, minimal, valid WAV file (silence), built with the
    standard library's own wave module — so mutagen's decode step in
    validate_audio actually succeeds against it, rather than a
    hand-rolled byte stub that only looks like audio."""
    buffer = BytesIO()
    frame_count = int(duration_seconds * frame_rate)
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(frame_rate)
        w.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


class FakeAudioProvider:
    """Stands in for the real Groq Whisper provider: transcribe returns
    a pre-baked TranscriptionResponse, or raises a pre-baked exception —
    never makes a network call. Records every call it receives."""

    def __init__(self, text: str | None = None, error: BaseException | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[tuple[bytes, str, str]] = []

    async def transcribe(self, audio_bytes: bytes, filename: str, model_id: str) -> TranscriptionResponse:
        self.calls.append((audio_bytes, filename, model_id))
        if self._error is not None:
            raise self._error
        assert self._text is not None
        return TranscriptionResponse(text=self._text, model_id=model_id, latency_ms=0.0)


class FakeTextProvider:
    """Stands in for the real Mistral text provider: complete_json
    returns a pre-built schema instance, or raises a pre-baked
    exception — never makes a network call."""

    def __init__(self, result: BaseModel | None = None, error: BaseException | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[str, str]] = []

    async def complete(self, *args: object, **kwargs: object) -> TextResponse:  # pragma: no cover
        raise NotImplementedError("FakeTextProvider only implements complete_json for these tests")

    async def complete_json(
        self,
        prompt: str,
        schema: type[SchemaT],
        model_id: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> SchemaT:
        self.calls.append((prompt, model_id))
        if self._error is not None:
            raise self._error
        assert self._result is not None
        assert isinstance(self._result, schema)
        return self._result
