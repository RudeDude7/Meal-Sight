"""Async token-bucket rate limiting, enforcing both RPS and TPM per model.

Two independent buckets per model: a request bucket (capacity 1, refilling
at rps tokens/sec — no bursting, since a call is either allowed or it
waits) and a token-budget bucket (capacity tpm, refilling at tpm/60 per
second — a full minute's budget can be spent at once if it's been idle,
matching how "tokens per minute" limits are normally enforced by
providers). acquire() waits for both to have room, then consumes from
both; models with no meaningful token cap (tpm == 0, e.g. Groq's Whisper
endpoint) skip the token bucket entirely rather than deadlocking against
an always-empty one.

Concurrency: each model has its own asyncio.Lock, not a single global
lock, so waiting for mistral-medium-2505's slow 0.42 RPS budget never
blocks a concurrent call to ministral-8b-2512's much faster budget. Two
concurrent callers for the *same* model do serialize — that's the point
of the lock: the bucket only has room for one call near its refill
boundary, and holding the lock across the wait is what makes "check, wait,
consume" atomic for that model.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from mealsight.config.settings import settings
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.providers.rate_limiter")


@dataclass(frozen=True, slots=True)
class WaitInfo:
    """Diagnostic snapshot of the most recent acquire() call for one model —
    not used by acquire()/reconcile() themselves, just exposed so callers
    (tooling, tests) can confirm which bucket actually constrained a wait."""

    wait_seconds: float
    request_wait_seconds: float
    token_wait_seconds: float
    binding_bucket: str  # "rps", "tpm", "both", or "none"


class _Bucket:
    def __init__(self, rate_per_second: float, capacity: float) -> None:
        self.rate = rate_per_second
        self.capacity = capacity
        self.tokens = capacity
        self._last_refill_at = time.monotonic()

    def refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill_at
        self._last_refill_at = now
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

    def time_until_available(self, amount: float) -> float:
        self.refill()
        if self.tokens >= amount:
            return 0.0
        return (amount - self.tokens) / self.rate

    def consume(self, amount: float) -> None:
        self.tokens -= amount

    def give_back(self, amount: float) -> None:
        self.tokens = min(self.capacity, self.tokens + amount)


class RateLimiter:
    """Async token-bucket limiter, one pair of buckets per model id."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._request_buckets: dict[str, _Bucket] = {}
        self._token_buckets: dict[str, _Bucket | None] = {}
        self._last_wait: dict[str, WaitInfo] = {}

    def _lock_for(self, model_id: str) -> asyncio.Lock:
        lock = self._locks.get(model_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[model_id] = lock
        return lock

    def _buckets_for(self, model_id: str) -> tuple[_Bucket, _Bucket | None]:
        if model_id not in self._request_buckets:
            spec = settings.get_rate_limit(model_id)
            self._request_buckets[model_id] = _Bucket(rate_per_second=spec.rps, capacity=1.0)
            self._token_buckets[model_id] = (
                _Bucket(rate_per_second=spec.tpm / 60.0, capacity=float(spec.tpm)) if spec.tpm > 0 else None
            )
        return self._request_buckets[model_id], self._token_buckets[model_id]

    async def acquire(self, model_id: str, estimated_tokens: int) -> None:
        """Waits until both the request bucket and the token-budget bucket
        (if this model has one) have room, then consumes from both."""
        async with self._lock_for(model_id):
            request_bucket, token_bucket = self._buckets_for(model_id)

            request_wait = request_bucket.time_until_available(1.0)
            token_wait = token_bucket.time_until_available(float(estimated_tokens)) if token_bucket else 0.0
            wait_seconds = max(request_wait, token_wait)

            if wait_seconds <= 0:
                binding_bucket = "none"
            elif request_wait == token_wait:
                binding_bucket = "both"
            elif request_wait > token_wait:
                binding_bucket = "rps"
            else:
                binding_bucket = "tpm"

            self._last_wait[model_id] = WaitInfo(
                wait_seconds=wait_seconds,
                request_wait_seconds=request_wait,
                token_wait_seconds=token_wait,
                binding_bucket=binding_bucket,
            )

            if wait_seconds > 0:
                logger.debug(
                    "rate_limiter_wait",
                    model_id=model_id,
                    wait_seconds=round(wait_seconds, 3),
                    binding_bucket=binding_bucket,
                    estimated_tokens=estimated_tokens,
                )
                await asyncio.sleep(wait_seconds)
                request_bucket.refill()
                if token_bucket is not None:
                    token_bucket.refill()

            request_bucket.consume(1.0)
            if token_bucket is not None:
                token_bucket.consume(float(estimated_tokens))

    def last_wait(self, model_id: str) -> WaitInfo | None:
        """Diagnostic accessor: what the most recent acquire() call for this
        model waited on, and which bucket (rps/tpm/both/none) was binding.
        Not used by acquire()/reconcile() themselves."""
        return self._last_wait.get(model_id)

    async def reconcile(self, model_id: str, actual_tokens: int, estimated_tokens: int) -> None:
        """Settles the difference between what was estimated before a call
        and what the provider actually reported afterward. If the estimate
        was too high, the surplus is given back to the token bucket; if it
        was too low, the deficit is taken out of it (a future acquire()
        for this model will simply wait a little longer)."""
        async with self._lock_for(model_id):
            _, token_bucket = self._buckets_for(model_id)
            if token_bucket is None:
                return
            difference = estimated_tokens - actual_tokens
            if difference >= 0:
                token_bucket.give_back(float(difference))
            else:
                token_bucket.consume(float(-difference))
