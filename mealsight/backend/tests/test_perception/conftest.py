"""Fixtures for mealsight.perception tests: a fresh pantry.db Database
per test, a real (Pillow-generated) minimal JPEG for validation tests
to decode, and a FakeVisionProvider standing in for the real Mistral
vision call — no live API call anywhere in this test package.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database
from mealsight.pantry.shelf_life import reset_shelf_life_cache
from mealsight.providers.base import TextResponse


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
