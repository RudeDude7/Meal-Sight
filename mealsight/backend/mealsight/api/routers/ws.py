"""WS /ws/{session_id} — connects to a running, queued, or already-
finished recommendation and streams its progress.

Three cases, handled directly rather than folded into one generic path:
  - unknown session_id: send one error message, close.
  - session already complete or failed: send the final result (or
    error) as a single message, close — no need to touch the live
    fan-out machinery at all for a session that's already done.
  - session pending or running: replay every message buffered so far
    (mealsight.api.streaming.SessionStream's own bounded buffer — this
    is what makes a mid-run OR reconnecting client catch up instead of
    silently missing everything before it connected), then subscribe
    for live messages and keep streaming until a complete/error message
    ends the run.

LIFECYCLE: a client disconnecting must never kill the running
recommendation — the agent run is an independent asyncio.Task
(mealsight.api.routers.recommend's own _run_in_background), already
decoupled from any one WebSocket connection's own lifetime; this
handler's only job on disconnect is to unsubscribe its own queue from
the session's SessionStream and return, never to reach for anything
that could cancel the background task. Every send is wrapped so a
disconnect discovered mid-send (the client went away between the last
successful send and this one) is handled the same way — cleanly, not
as an unhandled exception.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mealsight.api.dependencies import SessionsWSDep
from mealsight.api.messages import BaseWSMessage, CompleteMessage, ErrorMessage
from mealsight.api.sessions import RecommendationSession
from mealsight.api.streaming import TooManyConnectionsError
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.api.ws")

router = APIRouter(tags=["ws"])

# Starlette's own WebSocket close codes (RFC 6455): 1008 is "policy
# violation" — the closest standard code for both "no such session" and
# "too many connections," neither of which is a protocol error on the
# wire, just a request this endpoint won't honor.
POLICY_VIOLATION = 1008


def _error(session_id: str, code: str, message: str) -> ErrorMessage:
    return ErrorMessage(session_id=session_id, timestamp=datetime.now(UTC), code=code, message=message)


def _complete(session_id: str, result: dict[str, Any]) -> CompleteMessage:
    return CompleteMessage(session_id=session_id, timestamp=datetime.now(UTC), result=result)


async def _send(websocket: WebSocket, message: BaseWSMessage) -> bool:
    """Sends one message, swallowing a disconnect discovered mid-send
    rather than letting it propagate as an unhandled exception. Returns
    whether the send actually succeeded, so a caller looping over
    multiple messages (replay) can stop early instead of calling send
    again on a connection that's already gone."""
    try:
        await websocket.send_text(message.model_dump_json())
        return True
    except WebSocketDisconnect:
        return False
    except Exception:
        logger.warning("ws_send_failed_unexpectedly", session_id=message.session_id, exc_info=True)
        return False


@router.websocket("/ws/{session_id}")
async def recommendation_websocket(
    websocket: WebSocket, session_id: str, sessions: SessionsWSDep
) -> None:
    await websocket.accept()

    session: RecommendationSession | None = sessions.get(session_id)
    if session is None:
        await _send(websocket, _error(session_id, "not_found", "No such session."))
        await websocket.close(code=POLICY_VIOLATION)
        return

    if session.status == "complete":
        await _send(websocket, _complete(session_id, session.result or {}))
        await websocket.close()
        return

    if session.status == "failed":
        await _send(websocket, _error(session_id, "run_failed", session.error or "The run failed."))
        await websocket.close()
        return

    # pending or running: replay what's buffered so far, then subscribe
    # for live messages until the run genuinely ends.
    try:
        queue = session.stream.subscribe()
    except TooManyConnectionsError:
        await _send(
            websocket,
            _error(
                session_id,
                "too_many_connections",
                "This session already has the maximum number of live connections.",
            ),
        )
        await websocket.close(code=POLICY_VIOLATION)
        return

    try:
        for buffered_message in session.stream.replay():
            if not await _send(websocket, buffered_message):
                return

        while True:
            live_message = await queue.get()
            if not await _send(websocket, live_message):
                return
            if live_message.type in ("complete", "error"):
                await websocket.close()
                return
    except WebSocketDisconnect:
        logger.info("ws_client_disconnected", session_id=session_id)
    finally:
        session.stream.unsubscribe(queue)
