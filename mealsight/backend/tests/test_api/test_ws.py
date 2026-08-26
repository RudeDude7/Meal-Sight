"""Tests for WS /ws/{session_id} — using FastAPI's own TestClient
(Starlette under the hood), the standard, documented way to test a
WebSocket route: it runs the real app (real lifespan, real routing) in
a background thread with its own event loop, so a synchronous test can
drive a WebSocket connection while a real background asyncio.Task (the
recommendation itself) keeps running concurrently, exactly like
production.

No real agent graph runs here — run_recommendation is monkeypatched
(same convention as test_app.py's own recommend tests) so these tests
exercise the WEBSOCKET layer itself: buffering, replay, live delivery,
disconnect handling, unknown/complete/failed session handling. mealsight.
agent's own node tests already prove real nodes emit through
runtime.context.stream correctly; this file proves the WebSocket
endpoint delivers whatever's emitted, in order, to whoever's listening.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mealsight.api.app import create_app
from mealsight.api.messages import MESSAGE_CLASSES_BY_TYPE
from mealsight.api.rate_limit import SubmissionRateLimiter
from mealsight.api.sessions import SessionStore

recommend_module = importlib.import_module("mealsight.api.routers.recommend")


class _FakeManager:
    async def call_tool(self, server: str, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        raise AssertionError("no MCP call is expected in these WebSocket-layer tests")


def _lifespan(rate_limit: int = 100) -> Any:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.mcp_manager = _FakeManager()
        app.state.sessions = SessionStore()
        app.state.rate_limiter = SubmissionRateLimiter(limit=rate_limit)
        app.state.health_http_client = None
        yield

    return lifespan


def _client() -> TestClient:
    app = create_app(lifespan_override=_lifespan())
    return TestClient(app)


def _sessions(client: TestClient) -> SessionStore:
    return cast(FastAPI, client.app).state.sessions  # type: ignore[no-any-return]


# --------------------------------------------------------------------
# the three connection cases
# --------------------------------------------------------------------


def test_ws_unknown_session_errors_cleanly() -> None:
    with _client() as client, client.websocket_connect("/ws/does-not-exist") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "not_found"


def test_ws_completed_session_receives_final_result() -> None:
    with _client() as client:
        sessions = _sessions(client)
        session = sessions.create()
        sessions.mark_running(session.session_id, session.session_id)
        sessions.mark_complete(session.session_id, {"final_response": "Fake recipe"})

        with client.websocket_connect(f"/ws/{session.session_id}") as ws:
            message = ws.receive_json()

    assert message["type"] == "complete"
    assert message["result"] == {"final_response": "Fake recipe"}


def test_ws_failed_session_receives_an_error() -> None:
    with _client() as client:
        sessions = _sessions(client)
        session = sessions.create()
        sessions.mark_running(session.session_id, session.session_id)
        sessions.mark_failed(session.session_id, "boom")

        with client.websocket_connect(f"/ws/{session.session_id}") as ws:
            message = ws.receive_json()

    assert message["type"] == "error"
    assert message["message"] == "boom"


# --------------------------------------------------------------------
# ordering, buffering, live delivery
# --------------------------------------------------------------------


def test_ws_messages_arrive_in_order() -> None:
    with _client() as client:
        sessions = _sessions(client)
        session = sessions.create()
        sessions.mark_running(session.session_id, session.session_id)

        session.stream.emit("node_start", node="perceive")
        session.stream.emit("node_complete", node="perceive", duration_ms=12000.0)
        session.stream.emit("recipe_match", recipe_id="r1", name="Test", match_score=0.9, can_cook=True)

        with client.websocket_connect(f"/ws/{session.session_id}") as ws:
            first = ws.receive_json()
            second = ws.receive_json()
            third = ws.receive_json()

    assert [first["type"], second["type"], third["type"]] == [
        "node_start",
        "node_complete",
        "recipe_match",
    ]


def test_ws_mid_run_receives_buffered_then_live_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_recommendation(**kwargs: Any) -> dict[str, Any]:
        stream = kwargs["stream"]
        stream.emit("node_start", node="perceive")
        await asyncio.sleep(0.05)
        stream.emit("node_complete", node="perceive", duration_ms=50.0)
        await asyncio.sleep(0.3)
        stream.emit("recommendation", recipe_id="r1", summary="Pick this one.", available=True)
        return {"final_response": "Fake recipe", "stream_messages": []}

    monkeypatch.setattr(recommend_module, "run_recommendation", fake_run_recommendation)

    with _client() as client:
        start = client.post("/api/recommend", data={"text": "anything"})
        session_id = start.json()["session_id"]

        # Give the background task time to emit node_start/node_complete
        # (0.05s sleep) before connecting — this is the "mid-run,
        # buffered" half of the test.
        time.sleep(0.15)

        with client.websocket_connect(f"/ws/{session_id}") as ws:
            buffered_first = ws.receive_json()
            buffered_second = ws.receive_json()
            # live: arrives only after the fake's own 0.3s sleep resolves.
            live = ws.receive_json()
            complete = ws.receive_json()

    assert buffered_first["type"] == "node_start"
    assert buffered_second["type"] == "node_complete"
    assert live["type"] == "recommendation"
    assert complete["type"] == "complete"


# --------------------------------------------------------------------
# lifecycle: disconnect must not kill the run
# --------------------------------------------------------------------


def test_ws_client_disconnect_does_not_kill_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_recommendation(**kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(0.2)
        return {"final_response": "Fake recipe", "stream_messages": []}

    monkeypatch.setattr(recommend_module, "run_recommendation", fake_run_recommendation)

    with _client() as client:
        start = client.post("/api/recommend", data={"text": "anything"})
        session_id = start.json()["session_id"]

        with client.websocket_connect(f"/ws/{session_id}"):
            pass  # connect, then immediately disconnect

        time.sleep(0.4)
        poll = client.get(f"/api/recommend/{session_id}")

    assert poll.json()["status"] == "complete"
    assert poll.json()["result"]["final_response"] == "Fake recipe"


# --------------------------------------------------------------------
# schema validation
# --------------------------------------------------------------------


def test_every_message_type_validates_against_its_own_schema() -> None:
    payloads: dict[str, dict[str, Any]] = {
        "node_start": {"node": "perceive"},
        "node_complete": {"node": "perceive", "duration_ms": 12.5},
        "ingredient_found": {"modality": "vision", "message": "Found 3 items."},
        "recipe_match": {"recipe_id": "r1", "name": "Test", "match_score": 0.9, "can_cook": True},
        "recommendation": {"recipe_id": "r1", "summary": "Pick this.", "available": True},
        "stream_token": {"token": "hello"},
        "error": {"code": "internal_error", "message": "Something broke."},
        "complete": {"result": {"final_response": "ok"}},
    }
    assert set(payloads) == set(MESSAGE_CLASSES_BY_TYPE)

    now = datetime.now(UTC)
    for event_type, fields in payloads.items():
        message_cls = MESSAGE_CLASSES_BY_TYPE[event_type]
        message = message_cls(type=event_type, session_id="s1", timestamp=now, **fields)
        assert message.type == event_type
        assert message.session_id == "s1"


def test_message_schema_rejects_missing_required_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MESSAGE_CLASSES_BY_TYPE["recipe_match"](
            type="recipe_match", session_id="s1", timestamp=datetime.now(UTC)
        )
