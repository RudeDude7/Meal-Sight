#!/usr/bin/env python3
"""Proves the backend's token-bucket rate limiter actually engages against
a live API, rather than trusting the unit tests (which mock the network
entirely) to stand in for the real thing.

Makes 3 sequential calls to settings.REASONING_MODEL (mistral-medium-2505,
configured at 0.42 RPS) through the normal provider factory, then 3
sequential calls to settings.EXTRACTION_MODEL (ministral-8b-2512, 3.13
RPS). For each model, prints the elapsed time since the model's first call
for every call, the wall-clock delta between consecutive calls, and which
bucket (RPS or TPM) the limiter's own state says was binding — then a
PASS/FAIL verdict.

THE ACTUAL INVARIANT BEING CHECKED: the gap between when the limiter
*consumes* a token for call N and when it consumes one for call N+1 should
equal 1/rps. That consume instant isn't directly observable from outside,
but it's reconstructible exactly: consume_time(N) = (time the script called
acquire for N) + wait_seconds(N), where wait_seconds comes straight from
the limiter's own WaitInfo. This is deliberately NOT the same as comparing
wall-clock deltas between call *completions* — that raw delta is confounded
by each call's own network latency (notably, the very first call in a
fresh httpx client pays TLS/TCP connection setup that later calls reusing
the pooled connection don't), so it can legitimately run either above or
below 1/rps even when the limiter is enforcing the schedule exactly. The
reconstructed consume-to-consume gap has no such confound.

This makes real, billed API calls. Run with:
    backend/.venv/bin/python3 scripts/verify_rate_limiter.py
(uses the backend project's own virtualenv, so mealsight and its
dependencies are already installed there — no ad hoc --with flags needed.)
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mealsight.config.settings import settings  # noqa: E402
from mealsight.providers import close, get_rate_limiter, get_text_provider  # noqa: E402
from mealsight.providers.exceptions import ProviderError  # noqa: E402
from mealsight.providers.rate_limiter import WaitInfo  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CALLS_PER_MODEL = 3
PROMPT = "Reply with the single word: ok"
MAX_TOKENS = 5

# How far under the mathematically exact 1/rps the reconstructed
# consume-to-consume gap is allowed to fall before we call it a FAIL — this
# should only ever absorb a few milliseconds of event-loop scheduling
# jitter, since the token-bucket math itself is deterministic. A gap
# *larger* than 1/rps is never a failure (see _judge).
TOLERANCE = 0.10


@dataclass(frozen=True, slots=True)
class CallRecord:
    call_index: int
    attempt_started_at: float  # relative to this model's first attempt
    completed_at: float  # relative to this model's first attempt
    consume_time: float  # reconstructed: attempt_started_at + wait_seconds
    wall_clock_delta: float | None  # completed_at(N) - completed_at(N-1), for visibility only
    wait_info: WaitInfo | None
    error: str | None


@dataclass(frozen=True, slots=True)
class ModelVerification:
    model_key: str
    model_id: str
    configured_rps: float
    expected_gap_seconds: float
    calls: list[CallRecord]
    verdict: str
    reason: str


async def run_model_verification(model_key: str, model_id: str) -> ModelVerification:
    provider = get_text_provider()
    limiter = get_rate_limiter()
    rate_limit_spec = settings.get_rate_limit(model_id)
    expected_gap = 1.0 / rate_limit_spec.rps

    print(f"\n{'-' * 70}")
    print(f"{model_key} = {model_id!r}")
    print(f"configured: {rate_limit_spec.rps} RPS, {rate_limit_spec.tpm} TPM  ->  expected gap ~{expected_gap:.3f}s")
    print(f"{'-' * 70}")

    calls: list[CallRecord] = []
    origin: float | None = None
    previous_completed_at: float | None = None

    for i in range(1, CALLS_PER_MODEL + 1):
        logger.info("calling %s (%s), attempt %d/%d", model_key, model_id, i, CALLS_PER_MODEL)

        attempt_started_absolute = time.monotonic()
        if origin is None:
            origin = attempt_started_absolute
        attempt_started_at = attempt_started_absolute - origin

        error: str | None = None
        try:
            await provider.complete(PROMPT, model_id, max_tokens=MAX_TOKENS)
        except ProviderError as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.info("call %d failed: %s", i, error)

        completed_at = time.monotonic() - origin
        wall_clock_delta = None if previous_completed_at is None else completed_at - previous_completed_at
        previous_completed_at = completed_at

        wait_info = limiter.last_wait(model_id)
        consume_time = attempt_started_at + (wait_info.wait_seconds if wait_info is not None else 0.0)

        calls.append(
            CallRecord(
                call_index=i,
                attempt_started_at=attempt_started_at,
                completed_at=completed_at,
                consume_time=consume_time,
                wall_clock_delta=wall_clock_delta,
                wait_info=wait_info,
                error=error,
            )
        )

        delta_str = f"{wall_clock_delta:.3f}s" if wall_clock_delta is not None else "n/a (first call)"
        error_str = f"  ERROR: {error}" if error else ""
        print(f"  call {i}: completed_at={completed_at:.3f}s  wall_clock_delta={delta_str}{error_str}")
        if wait_info is not None:
            print(
                f"           waited {wait_info.wait_seconds:.3f}s before this call "
                f"(rps_wait={wait_info.request_wait_seconds:.3f}s, tpm_wait={wait_info.token_wait_seconds:.3f}s, "
                f"binding_bucket={wait_info.binding_bucket})  reconstructed consume_time={consume_time:.3f}s"
            )
        else:
            print("           no wait_info recorded (unexpected — limiter state not found for this model)")

    verdict, reason = _judge(calls, expected_gap)
    print(f"\n  VERDICT: {verdict} — {reason}")

    return ModelVerification(
        model_key=model_key,
        model_id=model_id,
        configured_rps=rate_limit_spec.rps,
        expected_gap_seconds=expected_gap,
        calls=calls,
        verdict=verdict,
        reason=reason,
    )


def _judge(calls: list[CallRecord], expected_gap: float) -> tuple[str, str]:
    errors = [c for c in calls if c.error is not None]
    if errors:
        return "FAIL", f"{len(errors)} call(s) failed: {errors[0].error}"

    if len(calls) < 2:
        return "FAIL", "not enough calls completed to measure a consume-to-consume gap"

    missing = [c for c in calls if c.wait_info is None]
    if missing:
        return (
            "FAIL",
            f"call {missing[0].call_index} has no recorded wait_info — "
            "limiter state was not found for this model",
        )

    consume_gaps = [calls[i].consume_time - calls[i - 1].consume_time for i in range(1, len(calls))]

    # Only a gap *smaller* than 1/rps means the limiter isn't engaging. A
    # gap *larger* than 1/rps is not a violation — it just means this
    # call's own network latency was already slower than the configured
    # rate, so there was nothing to throttle. Only the floor matters.
    floor = expected_gap * (1 - TOLERANCE)
    too_fast = [(i + 2, gap) for i, gap in enumerate(consume_gaps) if gap < floor]
    if too_fast:
        call_index, gap = too_fast[0]
        return (
            "FAIL",
            f"consume-to-consume gap before call {call_index} was {gap:.3f}s, under the {floor:.3f}s "
            f"floor (1/rps={expected_gap:.3f}s minus {TOLERANCE:.0%} tolerance) — the limiter is not "
            "enforcing the configured rate",
        )

    return (
        "PASS",
        f"reconstructed consume-to-consume gaps ({', '.join(f'{g:.3f}s' for g in consume_gaps)}) are all "
        f">= {floor:.3f}s, consistent with the configured 1/rps={expected_gap:.3f}s",
    )


async def main() -> int:
    print("MealSight Rate Limiter Live Verification")
    print("=" * 70)
    print(f"CALLS_PER_MODEL={CALLS_PER_MODEL}  prompt={PROMPT!r}  max_tokens={MAX_TOKENS}")

    results: list[ModelVerification] = []
    try:
        for model_key, model_id in (
            ("REASONING_MODEL", settings.REASONING_MODEL),
            ("EXTRACTION_MODEL", settings.EXTRACTION_MODEL),
        ):
            try:
                result = await run_model_verification(model_key, model_id)
            except ProviderError as exc:
                print(f"\n{'-' * 70}\n{model_key} = {model_id!r}\n{'-' * 70}")
                print(f"  VERDICT: FAIL — {type(exc).__name__}: {exc}")
                logger.info("model verification aborted for %s: %s", model_key, exc)
                result = ModelVerification(
                    model_key=model_key,
                    model_id=model_id,
                    configured_rps=settings.get_rate_limit(model_id).rps,
                    expected_gap_seconds=1.0 / settings.get_rate_limit(model_id).rps,
                    calls=[],
                    verdict="FAIL",
                    reason=f"{type(exc).__name__}: {exc}",
                )
            results.append(result)
    finally:
        await close()

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print("=" * 70)
    for result in results:
        print(
            f"{result.model_key:<20} {result.model_id:<24} "
            f"expected~{result.expected_gap_seconds:.3f}s  {result.verdict}"
        )

    all_passed = all(result.verdict == "PASS" for result in results)
    print(f"\nOverall: {'PASS' if all_passed else 'FAIL'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - top-level guard: report cleanly, no traceback dump
        print(f"\nFAIL — unexpected error running the verification: {type(exc).__name__}: {exc}")
        exit_code = 1
    raise SystemExit(exit_code)
