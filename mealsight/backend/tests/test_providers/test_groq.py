"""Tests for mealsight.providers.groq, mocked with respx — no live calls."""

from __future__ import annotations

import httpx
import pytest
import respx

from mealsight.config.settings import MODEL_RATE_LIMITS, RateLimitSpec
from mealsight.providers.exceptions import ProviderUnavailable
from mealsight.providers.groq import GroqProvider
from mealsight.providers.rate_limiter import RateLimiter

TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
TEST_MODEL = "test-whisper-model"


@pytest.fixture(autouse=True)
def _register_test_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(MODEL_RATE_LIMITS, TEST_MODEL, RateLimitSpec(rps=1000.0, tpm=0))


@pytest.fixture
def provider() -> GroqProvider:
    client = httpx.AsyncClient()
    return GroqProvider(client, RateLimiter())


@respx.mock
async def test_transcribe_returns_text_on_success(provider: GroqProvider) -> None:
    respx.post(TRANSCRIBE_URL).mock(return_value=httpx.Response(200, json={"text": "chop the onion"}))

    result = await provider.transcribe(b"fake-audio-bytes", "memo.mp3", TEST_MODEL)

    assert result.text == "chop the onion"
    assert result.model_id == TEST_MODEL


@respx.mock
async def test_cloudflare_1010_surfaces_as_provider_unavailable(provider: GroqProvider) -> None:
    cloudflare_body = (
        "<html><body>Sorry, you have been blocked</body></html>\nerror code: 1010"
    )
    respx.post(TRANSCRIBE_URL).mock(
        return_value=httpx.Response(403, text=cloudflare_body, headers={"Content-Type": "text/html"})
    )

    with pytest.raises(ProviderUnavailable) as exc_info:
        await provider.transcribe(b"fake-audio-bytes", "memo.mp3", TEST_MODEL)

    message = str(exc_info.value)
    assert "Cloudflare" in message
    assert "1010" in message
    assert exc_info.value.provider == "groq"


@respx.mock
async def test_request_carries_browser_like_user_agent(provider: GroqProvider) -> None:
    route = respx.post(TRANSCRIBE_URL).mock(return_value=httpx.Response(200, json={"text": "ok"}))

    await provider.transcribe(b"fake-audio-bytes", "memo.mp3", TEST_MODEL)

    sent_headers = route.calls[0].request.headers
    assert "Mozilla" in sent_headers["User-Agent"]
