"""The infrastructure circuit breaker, the preflight, and secret whitespace handling. No real API calls:
every provider response here is a constructed httpx.Response or a mock."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import eval.runner as runner
from eval import preflight
from eval.circuit import FAILURE_RATIO, MIN_CALLS, CircuitBreaker, InfrastructureFailure, breaker
from eval.compare import main as compare_main
from mealsight.config.settings import load_settings, settings
from mealsight.providers import outcomes
from mealsight.providers.retry import request_with_retry


class _Log:
    def warning(self, *a: Any, **k: Any) -> None: ...


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_retry_backoff", [0, 0, 0])
    yield  # type: ignore[misc]
    breaker.stop()


async def _call(status: int, calls: list[int]) -> None:
    async def make() -> httpx.Response:
        calls.append(status)
        return httpx.Response(status)

    # the pipeline above the provider swallows these failures exactly like this
    with contextlib.suppress(Exception):
        await request_with_retry(make, provider="mistral", model_id="m", logger=_Log())


async def test_every_call_rate_limited_trips_the_breaker_at_the_threshold_not_at_the_end() -> None:
    cb = CircuitBreaker()
    cb.start("dimension1_test")
    http_attempts: list[int] = []
    finished = 0
    with pytest.raises(InfrastructureFailure) as stopped:
        for _ in range(100):  # a long dimension; it must NOT run all of them
            cb.check()
            await _call(429, http_attempts)
            finished += 1
    cb.stop()
    assert finished == MIN_CALLS, "aborts as soon as the minimum sample is reached"
    assert len(http_attempts) == MIN_CALLS * 4, "each failed call already used its 4 attempts; no real I/O"
    assert stopped.value.detail["by_outcome"] == {outcomes.RATE_LIMITED: MIN_CALLS}
    assert "infrastructure failure" in stopped.value.reason


async def test_healthy_calls_and_an_occasional_failure_do_not_trip_it() -> None:
    cb = CircuitBreaker()
    cb.start("d")
    sink: list[int] = []
    for _ in range(9):
        await _call(200, sink)
    await _call(429, sink)  # one failure in ten is under the 50% threshold
    cb.check()
    cb.stop()


async def test_a_rejected_key_counts_as_infrastructure_too() -> None:
    cb = CircuitBreaker()
    cb.start("d")
    sink: list[int] = []
    for _ in range(MIN_CALLS):
        await _call(401, sink)
    cb.stop()
    with pytest.raises(InfrastructureFailure):
        cb.check()
    assert len(sink) == MIN_CALLS, "401 is not retried"


def test_the_threshold_values_are_the_documented_ones() -> None:
    assert (MIN_CALLS, FAILURE_RATIO) == (5, 0.5)


async def test_an_aborted_run_is_recorded_not_scored_and_the_gate_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_dimension1(case_limit: int | None = None) -> Any:
        breaker.start("dimension1_ingredient_recognition")
        sink: list[int] = []
        for _ in range(20):
            breaker.check()
            await _call(429, sink)
        raise AssertionError("the breaker should have stopped this")

    async def no_pantry() -> dict[str, Any]:
        return {"pantry_present": False}

    async def no_data() -> dict[str, str]:
        return {}

    monkeypatch.setattr(runner, "run_dimension1", fake_dimension1)
    monkeypatch.setattr(runner, "pantry_snapshot", no_pantry)
    monkeypatch.setattr(runner, "data_versions", no_data)
    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "close_all", _noop)

    scorecard = await runner.run_eval(dimensions=("dimension1",))
    assert scorecard.aborted and not scorecard.passed
    assert "rate_limited" in (scorecard.abort_reason or "")
    assert scorecard.abort_detail["calls"] == MIN_CALLS
    written = json.loads(next(tmp_path.glob("run_*.json")).read_text())
    assert written["aborted"] is True and written["dimensions"] == []

    card = next(tmp_path.glob("run_*.json"))
    assert compare_main([str(card)]) == 2
    assert compare_main([str(card), "--update", "--reason", "x"]) == 2, "never accepted as a baseline"
    assert "ABORTED" in capsys.readouterr().err


async def _noop() -> None: ...


# ---- secrets ------------------------------------------------------------------------------------------


def test_a_pasted_trailing_newline_or_space_is_stripped_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "abc123\n")
    monkeypatch.setenv("GROQ_API_KEY", "  def456 ")
    monkeypatch.setenv("OPENWEATHER_API_KEY", "ghi789\r\n")
    loaded = load_settings(env_file=None)
    assert loaded.mistral_api_key.get_secret_value() == "abc123"
    assert loaded.groq_api_key.get_secret_value() == "def456"
    assert loaded.openweather_api_key is not None
    assert loaded.openweather_api_key.get_secret_value() == "ghi789"


def test_a_whitespace_only_required_key_is_still_rejected_as_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", " \n")
    monkeypatch.setenv("GROQ_API_KEY", "ok")
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        load_settings(env_file=None)


# ---- preflight ----------------------------------------------------------------------------------------


def test_preflight_reports_length_and_whitespace_but_never_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-very-secret-value"
    monkeypatch.setenv("MISTRAL_API_KEY", secret + "\n")
    note = preflight.describe_key("MISTRAL_API_KEY")
    text = " ".join(note)
    assert f"length {len(secret) + 1}" in text and "TRAILING" in text and "control character" in text
    assert secret not in text and secret[:4] not in text
    monkeypatch.setenv("MISTRAL_API_KEY", secret)
    assert "no leading or trailing whitespace" in " ".join(preflight.describe_key("MISTRAL_API_KEY"))
    assert preflight.whitespace_padded("MISTRAL_API_KEY") is False


@pytest.mark.parametrize(
    ("status", "headers", "ok", "needle"),
    [
        (200, {"x-ratelimit-limit-req-minute": "60"}, True, "OK"),
        (429, {"retry-after": "30"}, False, "RATE LIMITED"),
        (401, {}, False, "REJECTED the key"),
        (503, {}, False, "server-side"),
        (200, {"x-ratelimit-limit-req-minute": "2"}, False, "allows only 2 requests/minute"),
    ],
)
def test_preflight_verdicts(status: int, headers: dict[str, str], ok: bool, needle: str) -> None:
    result = preflight.judge("mistral", httpx.Response(status, headers=headers), ["note"], padded=False)
    assert result.ok is ok and needle in result.summary


def test_preflight_warns_when_the_secret_was_padded() -> None:
    result = preflight.judge("mistral", httpx.Response(200), ["note"], padded=True)
    assert result.ok and any("WARNING" in line and "whitespace" in line for line in result.lines)
