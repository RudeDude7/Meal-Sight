"""Honest progress for a stage that is waiting on a provider call.

Under the free tier a call can spend most of its time NOT running but queued behind our own rate limiter
(ministral-8b-2512 is limited to 2 requests a minute, so a second call waits about 30 s). "Still
thinking..." for 30 s while the system is idle would be a small lie. This module reads the limiter's own
state (RateLimiter.last_wait) and says what is really happening, with a countdown.

A countdown rather than a one-off explanation: the heartbeat repeats every couple of seconds and the UI
replaces the previous line in place (one line per modality in the live feed, one per pipeline step), so a
changing number is the visible proof the system is alive, and it never piles up into a wall of text.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from mealsight.config.settings import settings
from mealsight.providers.rate_limiter import WaitInfo, WaitTracker, current_wait_tracker

T = TypeVar("T")

# No gap between progress events may exceed 3 s (the Phase 7.2 standard). A tick that fires at exactly 3.0 s
# lands a hair over, so the heartbeat runs at 2.5 s.
HEARTBEAT_INTERVAL_SECONDS = 2.5


def describe_wait(model_id: str, info: WaitInfo | None, *, now: float | None = None) -> str | None:
    """What the user should be told if THIS call (whose limiter wait is `info`) is currently queued behind
    the rate limiter, else None (the call is in flight with the provider, or never had to wait)."""
    if info is None or info.wait_seconds <= 0:
        return None
    remaining = info.wait_seconds - ((now if now is not None else time.monotonic()) - info.started_at)
    if remaining <= 0.5:
        return None
    try:
        spec = settings.get_rate_limit(model_id)
    except KeyError:
        return f"Waiting on the provider's rate limit, about {remaining:.0f}s to go."
    per_minute = spec.rps * 60
    if info.binding_bucket in ("rps", "both") and per_minute < 30:
        reason = (
            f"the free tier allows {per_minute:.0f} request{'s' if per_minute != 1 else ''} a minute "
            f"(one every {1 / spec.rps:.0f}s)"
        )
    elif info.binding_bucket == "tpm":
        reason = f"the free tier allows {spec.tpm:,} tokens a minute"
    else:
        reason = "the provider's rate limit"
    return f"Waiting for the rate limit, not computing: {reason}. About {remaining:.0f}s to go."


async def run_with_heartbeat(
    awaitable: Awaitable[T],
    *,
    model_id: str,
    emit: Callable[[str], None],
    idle_texts: tuple[str, ...],
    interval: float | None = None,
) -> T:
    """Awaits `awaitable`, calling `emit(text)` every interval while it is still running. The text is the
    limiter countdown when the call is queued behind the rate limiter, otherwise the next of `idle_texts`
    (a real description of what the provider is doing). Peeks with asyncio.wait; never cancels or alters
    the call."""
    # The tracker is made current BEFORE the task is created so the task (and anything it spawns) inherits
    # it and the limiter can report this call's own wait, not another concurrent call's.
    tracker = WaitTracker()
    token = current_wait_tracker.set(tracker)
    try:
        task: asyncio.Future[T] = asyncio.ensure_future(awaitable)
    finally:
        current_wait_tracker.reset(token)
    index = 0
    while True:
        done, _ = await asyncio.wait(
            {task}, timeout=interval if interval is not None else HEARTBEAT_INTERVAL_SECONDS
        )
        if task in done:
            return await task
        waiting = describe_wait(model_id, tracker.info)
        if waiting is not None:
            emit(waiting)
        else:
            emit(idle_texts[index % len(idle_texts)])
            index += 1
