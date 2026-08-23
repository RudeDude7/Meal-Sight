"""Tests for mealsight.providers.retry, in isolation from any real provider."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from mealsight.config.settings import settings
from mealsight.providers.exceptions import ProviderUnavailable, RateLimitExceeded
from mealsight.providers.retry import request_with_retry


class _RecordingLogger:
    def __init__(self) -> None:
        self.warnings: list[dict[str, Any]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.warnings.append({"event": event, **kwargs})


def _responses(*statuses_and_headers: tuple[int, dict[str, str]]) -> Callable[[], Awaitable[httpx.Response]]:
    queue = list(statuses_and_headers)

    async def make_request() -> httpx.Response:
        status, headers = queue.pop(0)
        return httpx.Response(status, headers=headers, json={"ok": True})

    return make_request


async def _fake_sleep_recorder(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr("mealsight.providers.retry.asyncio.sleep", fake_sleep)
    return recorded


async def test_429_with_retry_after_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = await _fake_sleep_recorder(monkeypatch)
    make_request = _responses((429, {"Retry-After": "7"}), (200, {}))

    response = await request_with_retry(
        make_request, provider="test", model_id="m", logger=_RecordingLogger()
    )

    assert response.status_code == 200
    assert recorded == [7.0]


async def test_429_without_retry_after_uses_backoff_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = await _fake_sleep_recorder(monkeypatch)
    make_request = _responses((429, {}), (200, {}))

    await request_with_retry(make_request, provider="test", model_id="m", logger=_RecordingLogger())

    assert recorded == [float(settings.llm_retry_backoff[0])]


async def test_4xx_other_than_429_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = await _fake_sleep_recorder(monkeypatch)
    calls = {"count": 0}

    async def make_request() -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    response = await request_with_retry(
        make_request, provider="test", model_id="m", logger=_RecordingLogger()
    )

    assert response.status_code == 400
    assert calls["count"] == 1
    assert recorded == []


async def test_5xx_is_retried_per_backoff_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = await _fake_sleep_recorder(monkeypatch)
    make_request = _responses((500, {}), (500, {}), (200, {}))
    logger = _RecordingLogger()

    response = await request_with_retry(make_request, provider="test", model_id="m", logger=logger)

    assert response.status_code == 200
    assert recorded == [float(settings.llm_retry_backoff[0]), float(settings.llm_retry_backoff[1])]
    assert len(logger.warnings) == 2
    assert logger.warnings[0]["attempt"] == 1
    assert logger.warnings[1]["attempt"] == 2


async def test_5xx_raises_provider_unavailable_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _fake_sleep_recorder(monkeypatch)
    always_500 = _responses(*[(500, {})] * (settings.llm_max_retries + 1))

    with pytest.raises(ProviderUnavailable):
        await request_with_retry(always_500, provider="test", model_id="m", logger=_RecordingLogger())


async def test_429_raises_rate_limit_exceeded_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _fake_sleep_recorder(monkeypatch)
    always_429 = _responses(*[(429, {})] * (settings.llm_max_retries + 1))

    with pytest.raises(RateLimitExceeded):
        await request_with_retry(always_429, provider="test", model_id="m", logger=_RecordingLogger())
