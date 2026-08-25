"""In-memory session store backing POST /api/recommend's 202-Accepted,
poll-for-status pattern: one RecommendationSession per session_id,
mutated in place as the background agent run progresses from pending
through running to complete or failed.

In-memory, not persisted: matches the single-process, single
long-lived-MCPClientManager design of mealsight.api.app's own lifespan
(mealsight.api.rate_limit's own docstring makes the identical point for
the same reason) — a restart loses in-flight sessions, which is an
acceptable, honest trade-off for the current deployment shape, not
something silently glossed over.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

SessionStatus = Literal["pending", "running", "complete", "failed"]


@dataclass
class RecommendationSession:
    session_id: str
    status: SessionStatus = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trace_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class SessionStore:
    """Every method here is synchronous and non-blocking (plain dict
    reads/writes) — safe to call from the request handler and the
    background task without a lock, since asyncio only switches tasks
    at an `await`, and nothing here awaits."""

    def __init__(self) -> None:
        self._sessions: dict[str, RecommendationSession] = {}

    def create(self) -> RecommendationSession:
        session = RecommendationSession(session_id=str(uuid.uuid4()))
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> RecommendationSession | None:
        return self._sessions.get(session_id)

    def mark_running(self, session_id: str, trace_id: str) -> None:
        session = self._sessions[session_id]
        session.status = "running"
        session.trace_id = trace_id

    def mark_complete(self, session_id: str, result: dict[str, Any]) -> None:
        session = self._sessions[session_id]
        session.status = "complete"
        session.result = result

    def mark_failed(self, session_id: str, error: str) -> None:
        session = self._sessions[session_id]
        session.status = "failed"
        session.error = error
