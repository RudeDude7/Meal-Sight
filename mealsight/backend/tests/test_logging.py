"""Tests for mealsight.utils.logging."""

from __future__ import annotations

import asyncio
import json

import pytest

from mealsight.config.settings import settings
from mealsight.utils.logging import bind_trace_id, get_logger, timed_block


def test_trace_id_propagates_into_emitted_log_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    bind_trace_id("trace-abc-123")

    logger = get_logger("test-service")
    logger.info("something happened")

    captured = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert captured["trace_id"] == "trace-abc-123"


async def _log_from_inner_coroutine() -> None:
    logger = get_logger("inner")
    logger.info("inner event")


def test_trace_id_propagates_across_await_boundary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    bind_trace_id("trace-across-await")

    async def outer() -> None:
        await asyncio.sleep(0)
        await _log_from_inner_coroutine()

    asyncio.run(outer())

    captured = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert captured["trace_id"] == "trace-across-await"


def test_logger_emits_valid_json_in_production(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "environment", "production")

    logger = get_logger("json-service")
    logger.info("hello world", foo="bar")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["event"] == "hello world"
    assert payload["service"] == "json-service"
    assert payload["foo"] == "bar"
    assert "timestamp" in payload
    assert "level" in payload


def test_timed_block_emits_duration_ms(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    logger = get_logger("timing-service")

    with timed_block(logger, "did_a_thing"):
        pass

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["event"] == "did_a_thing"
    assert isinstance(payload["duration_ms"], (int, float))
    assert payload["duration_ms"] >= 0
