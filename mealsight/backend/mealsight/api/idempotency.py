"""In-process idempotency store for POST /api/cook — the only path in
this whole API that mutates meal history and deducts from the pantry,
which makes a double-clicked button (or a client retry after a slow
response it gave up waiting on) a real risk: two identical requests
must never double-log a meal or double-deduct a pantry.

APPROACH CHOSEN: accept an OPTIONAL client-supplied idempotency_key in
the request body; when the caller doesn't supply one, derive one from
recipe_id plus a coarse time window (derive_idempotency_key). A repeat
call with the SAME key — whether client-supplied or derived — replays
the exact response the first call computed, without running compute()
(log_meal + remove_items) a second time.

Why a derived key exists at all, rather than requiring the client to
always supply one: a real frontend button-double-click is the common
case this exists to guard, and forcing every caller to generate and
track its own UUID for that is friction a coarse, recipe-scoped time
window removes for free. Why the window is coarse (IDEMPOTENCY_WINDOW_
SECONDS, 30s) rather than fine-grained: two GENUINELY separate cook
confirmations of the same recipe minutes apart (a real, if unusual,
same-day repeat) must still both be recorded — a window has to be long
enough to absorb a slow double-tap or a client retry, but short enough
that it never conflates two real, independent cooking events. A
sophisticated client that needs a stronger guarantee (e.g. an offline-
first mobile client resubmitting after a real reconnect, possibly well
past 30s) should always supply its own idempotency_key rather than rely
on the derived one.

run_once's own per-key asyncio.Lock is what makes this correct under
CONCURRENT duplicate requests, not just sequential ones: two requests
racing in with the identical key both reach the lock, one runs
compute() first and caches the result, the other then acquires the
lock, finds the cache already populated, and returns that instead of
running compute() a second time — the same "check, then maybe run, then
cache, all under one lock" shape mealsight.providers.rate_limiter.
RateLimiter's own per-model lock already uses for the identical reason.

Whatever compute() returns — success OR a partial failure (see
mealsight.api.routers.cook's own module docstring on the log_meal/
remove_items ordering) — is cached as-is and never re-run for that key.
This is a deliberate choice, not an oversight: retrying a PARTIALLY
failed cook confirmation under the same key could easily double-deduct
whatever partially succeeded the first time, since remove_items itself
isn't naturally safe to call twice for the same items. A genuinely
failed cook confirmation needs a fresh idempotency_key (or to wait out
the window) to retry, not automatic retry-until-success semantics.

In-process, not backed by Redis or any external store — the identical
trade-off, and the identical reasoning, mealsight.api.sessions.
SessionStore and mealsight.api.rate_limit.SubmissionRateLimiter already
made for the same single-process, single-long-lived-MCPClientManager
deployment shape.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

IDEMPOTENCY_WINDOW_SECONDS = 30.0
IDEMPOTENCY_TTL_SECONDS = 3600.0


def derive_idempotency_key(recipe_id: str) -> str:
    window = int(time.time() // IDEMPOTENCY_WINDOW_SECONDS)
    return f"{recipe_id}:{window}"


class IdempotencyStore:
    def __init__(self) -> None:
        self._results: dict[str, tuple[float, dict[str, Any]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def run_once(
        self, key: str, compute: Callable[[], Awaitable[dict[str, Any]]]
    ) -> tuple[dict[str, Any], bool]:
        """Returns (response, was_replayed). Runs compute() at most once
        per key, ever (until swept) — a concurrent or later call with
        the same key gets the exact response already stored instead of
        running compute() again."""
        async with self._lock_for(key):
            cached = self._results.get(key)
            if cached is not None:
                return cached[1], True
            response = await compute()
            self._results[key] = (time.monotonic(), response)
            return response, False

    def sweep_expired(self, ttl_seconds: float = IDEMPOTENCY_TTL_SECONDS) -> int:
        """Mirrors mealsight.api.sessions.SessionStore.sweep_expired —
        called periodically from mealsight.api.app's own lifespan, never
        from a request handler. Returns how many entries were removed,
        purely for logging."""
        now = time.monotonic()
        expired = [key for key, (recorded_at, _) in self._results.items() if now - recorded_at > ttl_seconds]
        for key in expired:
            del self._results[key]
            self._locks.pop(key, None)
        return len(expired)
