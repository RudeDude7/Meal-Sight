"""Confirms the logging contextvar's trace_id shows up in provider log
lines — the loggers providers use come from mealsight.utils.logging, so
this is really confirming that wiring, not re-testing the logger itself."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from mealsight.config.settings import MODEL_RATE_LIMITS, RateLimitSpec, settings
from mealsight.providers.mistral import MistralProvider
from mealsight.providers.rate_limiter import RateLimiter
from mealsight.utils.logging import bind_trace_id

CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
TEST_MODEL = "test-tracing-model"


@respx.mock
async def test_trace_id_appears_in_provider_log_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setitem(MODEL_RATE_LIMITS, TEST_MODEL, RateLimitSpec(rps=1000.0, tpm=1_000_000))
    bind_trace_id("trace-in-provider-logs")

    # A retryable 500 followed by a success is a convenient way to make the
    # provider actually emit a log line (retry.py logs a warning per retry)
    # without needing debug-level output enabled.
    route = respx.post(CHAT_URL)
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "banana"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        ),
    ]

    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("mealsight.providers.retry.asyncio.sleep", fake_sleep)

    client = httpx.AsyncClient()
    provider = MistralProvider(client, RateLimiter())
    await provider.complete("what's in the fridge?", TEST_MODEL)

    lines = [line for line in capsys.readouterr().err.strip().splitlines() if line]
    parsed = [json.loads(line) for line in lines]
    assert any(entry.get("trace_id") == "trace-in-provider-logs" for entry in parsed)
