"""A simple in-process, per-IP sliding-window rate limiter for POST
/api/recommend specifically — a "submission" starts a real agent run
(several LLM calls, a cascade of MCP tool calls), not a cheap read, so
it gets its own tighter budget than general request traffic.

Deliberately in-process, not backed by Redis or any external store:
this API runs as a single process holding one long-lived
MCPClientManager (mealsight.api.app's own lifespan) — there is no
multi-process/multi-worker deployment to coordinate across yet, so an
in-memory dict is the honest, right-sized choice, not a placeholder for
something more distributed the current deployment doesn't have.
"""

from __future__ import annotations

import time
from collections import defaultdict

from mealsight.config.settings import settings

WINDOW_SECONDS = 60.0


class SubmissionRateLimiter:
    """Sliding window: for a given key (typically a client IP), records
    a timestamp per submission and rejects once more than `limit`
    timestamps fall within the last WINDOW_SECONDS. Old timestamps are
    pruned lazily, on the next check for that same key — no background
    sweep needed for an in-process limiter this small."""

    def __init__(self, limit: int | None = None) -> None:
        self._limit = limit if limit is not None else settings.max_submissions_per_minute
        self._submissions: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        """Records this submission attempt and returns whether it's
        allowed. Always records — including a rejected attempt — since
        the window is sliding, not reset-on-reject, and a would-be
        submission still occupies a slot in this key's own history for
        the purpose of judging the NEXT one."""
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        recent = [t for t in self._submissions[key] if t > cutoff]
        recent.append(now)
        self._submissions[key] = recent
        return len(recent) <= self._limit

    def reset(self) -> None:
        """Test/diagnostic use only — clears every key's own history."""
        self._submissions.clear()
