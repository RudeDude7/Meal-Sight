"""Live provider smoke tests — one real call per provider, real network,
real API keys from .env. Skipped by default (see the `integration` marker
in pyproject.toml); run explicitly with:

    uv run pytest -m integration tests/integration
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from mealsight.config.settings import REPO_ROOT, settings
from mealsight.providers import close, get_audio_provider, get_text_provider, get_vision_provider

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _fresh_providers_per_test() -> AsyncIterator[None]:
    # The provider singletons cache one httpx.AsyncClient at module scope,
    # but pytest-asyncio gives each test function its own event loop by
    # default — reusing a client (and its underlying connections) across
    # loops raises "Event loop is closed". Closing here forces the next
    # test to build a fresh client bound to its own loop.
    yield
    await close()


async def test_text_provider_completes_a_simple_prompt() -> None:
    provider = get_text_provider()
    response = await provider.complete("Reply with exactly the word: pong", settings.REASONING_MODEL)
    assert response.text
    assert response.total_tokens > 0


async def test_vision_provider_analyzes_a_real_fridge_photo() -> None:
    image_path = REPO_ROOT / "test_data" / "images" / "photo_01.jpg"
    provider = get_vision_provider()
    response = await provider.analyze_image(
        image_path.read_bytes(), "List one food item you see.", settings.VISION_MODEL
    )
    assert response.text


async def test_audio_provider_transcribes_a_real_voice_memo() -> None:
    audio_path = REPO_ROOT / "test_data" / "audio" / "memo_01.mp3"
    provider = get_audio_provider()
    response = await provider.transcribe(audio_path.read_bytes(), "memo_01.mp3", settings.AUDIO_MODEL)
    assert response.text
