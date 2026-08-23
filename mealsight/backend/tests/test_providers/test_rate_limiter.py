"""Tests for mealsight.providers.rate_limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from mealsight.config.settings import MODEL_RATE_LIMITS, RateLimitSpec
from mealsight.providers.rate_limiter import RateLimiter

FAST_MODEL = "test-fast-model"
FAST_RPS = 5.0


@pytest.fixture(autouse=True)
def _register_fast_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(MODEL_RATE_LIMITS, FAST_MODEL, RateLimitSpec(rps=FAST_RPS, tpm=1_000_000))


async def test_token_bucket_blocks_and_releases_at_known_rps() -> None:
    limiter = RateLimiter()
    interval = 1.0 / FAST_RPS

    started = time.monotonic()
    for _ in range(3):
        await limiter.acquire(FAST_MODEL, estimated_tokens=1)
    elapsed = time.monotonic() - started

    # First call is free (bucket starts full); the next two each cost one
    # interval's wait, so three calls take roughly 2 intervals, not 0.
    assert elapsed >= interval * 1.5
    assert elapsed < interval * 4


async def test_concurrent_acquires_serialize() -> None:
    limiter = RateLimiter()
    interval = 1.0 / FAST_RPS

    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire(FAST_MODEL, estimated_tokens=1) for _ in range(3)))
    elapsed = time.monotonic() - started

    # If concurrent callers didn't serialize against the same bucket, all
    # three would return almost immediately instead of paying for two
    # intervals' worth of waiting between them.
    assert elapsed >= interval * 1.5


async def test_reconcile_gives_back_overestimated_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(MODEL_RATE_LIMITS, "test-token-model", RateLimitSpec(rps=1000.0, tpm=100))
    limiter = RateLimiter()
    await limiter.acquire("test-token-model", estimated_tokens=100)

    token_bucket = limiter._buckets_for("test-token-model")[1]
    assert token_bucket is not None
    assert token_bucket.tokens == pytest.approx(0.0)

    await limiter.reconcile("test-token-model", actual_tokens=50, estimated_tokens=100)

    assert token_bucket.tokens == pytest.approx(50.0)


async def test_reconcile_takes_back_underestimated_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(MODEL_RATE_LIMITS, "test-token-model-2", RateLimitSpec(rps=1000.0, tpm=100))
    limiter = RateLimiter()
    await limiter.acquire("test-token-model-2", estimated_tokens=50)

    token_bucket = limiter._buckets_for("test-token-model-2")[1]
    assert token_bucket is not None
    assert token_bucket.tokens == pytest.approx(50.0)

    await limiter.reconcile("test-token-model-2", actual_tokens=90, estimated_tokens=50)

    assert token_bucket.tokens == pytest.approx(10.0)


async def test_model_with_zero_tpm_has_no_token_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(MODEL_RATE_LIMITS, "test-no-tpm-model", RateLimitSpec(rps=1000.0, tpm=0))
    limiter = RateLimiter()

    # Should not hang waiting on a token bucket that can never have room.
    await asyncio.wait_for(limiter.acquire("test-no-tpm-model", estimated_tokens=999_999), timeout=1.0)

    request_bucket, token_bucket = limiter._buckets_for("test-no-tpm-model")
    assert token_bucket is None
