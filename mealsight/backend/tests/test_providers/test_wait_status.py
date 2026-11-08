"""Honest wait reporting: the limiter countdown, per-call attribution, and no head-of-line blocking."""

from __future__ import annotations

import asyncio
import time

from mealsight.agent.wait_status import describe_wait, run_with_heartbeat
from mealsight.providers.rate_limiter import RateLimiter, WaitInfo

MODEL = "ministral-8b-2512"


def _info(wait: float, bucket: str = "rps", started_ago: float = 0.0) -> WaitInfo:
    return WaitInfo(wait, wait, 0.0, bucket, started_at=time.monotonic() - started_ago)


def test_a_queued_call_gets_a_countdown_that_names_the_real_reason() -> None:
    text = describe_wait(MODEL, _info(30.0, started_ago=10.0))
    assert text is not None
    assert "rate limit, not computing" in text and "2 requests a minute" in text
    assert "one every 30s" in text and "20s to go" in text


def test_a_finished_wait_or_no_wait_says_nothing_about_the_limiter() -> None:
    assert describe_wait(MODEL, None) is None
    assert describe_wait(MODEL, _info(0.0)) is None
    assert describe_wait(MODEL, _info(30.0, started_ago=29.9)) is None


async def test_heartbeat_reports_the_countdown_for_the_call_that_waits_not_for_its_neighbour() -> None:
    limiter = RateLimiter()
    await limiter.acquire(MODEL, 10)  # uses the free slot

    async def queued() -> str:
        await limiter.acquire(MODEL, 10)  # has to wait ~30 s; the test cancels long before
        return "done"

    async def in_flight() -> str:
        await asyncio.sleep(0.25)
        return "done"

    queued_lines: list[str] = []
    flying_lines: list[str] = []
    waiting = asyncio.create_task(
        run_with_heartbeat(
            queued(), model_id=MODEL, emit=queued_lines.append, idle_texts=("idle",), interval=0.05
        )
    )
    await asyncio.sleep(0.02)
    await run_with_heartbeat(
        in_flight(), model_id=MODEL, emit=flying_lines.append, idle_texts=("idle",), interval=0.05
    )
    waiting.cancel()
    assert queued_lines and all("rate limit" in line for line in queued_lines)
    assert flying_lines
    assert set(flying_lines) == {"idle"}, "an in-flight call must not claim to be rate limited"


async def test_a_finished_call_is_not_blocked_behind_another_calls_wait() -> None:
    limiter = RateLimiter()
    await limiter.acquire(MODEL, 10)
    sleeper = asyncio.create_task(limiter.acquire(MODEL, 10))  # holds the model lock while it waits ~30 s
    await asyncio.sleep(0.05)
    started = time.monotonic()
    await asyncio.wait_for(limiter.reconcile(MODEL, 5, 10), timeout=1.0)
    assert time.monotonic() - started < 0.5
    sleeper.cancel()
