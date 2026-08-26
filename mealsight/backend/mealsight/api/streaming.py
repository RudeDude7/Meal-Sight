"""SessionStream — the concrete implementation of mealsight.agent.
context.StreamSink, one instance per recommendation session. Holds a
BOUNDED buffer of every message emitted so far (so a client connecting
mid-run, or reconnecting, gets what it missed before continuing live)
and fans each new message out to every currently-subscribed WebSocket
via that connection's own asyncio.Queue.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
from typing import Any

from mealsight.api.messages import MESSAGE_CLASSES_BY_TYPE, BaseWSMessage

# Generous relative to a real run's own message count (perceive alone
# emits at most 3, match_rank at most TOP_N_CANDIDATES_TO_MATCH=10,
# plus one node_start/node_complete pair per of the eleven nodes) — this
# bounds memory for a session nobody ever drains, not a limit expected
# to bind in normal operation.
DEFAULT_BUFFER_SIZE = 500

# A small, deliberate cap — this is a single-user recommendation session,
# not a broadcast channel; a handful of tabs/devices watching the same
# run is the realistic ceiling, not something to size for fan-out at
# scale.
MAX_CONNECTIONS_PER_SESSION = 4


class TooManyConnectionsError(Exception):
    """Raised by SessionStream.subscribe() when a session already has
    MAX_CONNECTIONS_PER_SESSION live subscribers."""


class SessionStream:
    def __init__(self, session_id: str, buffer_size: int = DEFAULT_BUFFER_SIZE) -> None:
        self.session_id = session_id
        self._buffer: deque[BaseWSMessage] = deque(maxlen=buffer_size)
        self._subscribers: list[asyncio.Queue[BaseWSMessage]] = []

    def emit(self, event_type: str, **fields: Any) -> None:
        """The StreamSink protocol method every agent node calls —
        synchronous and non-blocking (asyncio.Queue.put_nowait), so a
        node's own call site never needs to await it."""
        message_cls = MESSAGE_CLASSES_BY_TYPE[event_type]
        message = message_cls(
            session_id=self.session_id, timestamp=datetime.now(UTC), **fields
        )
        self._buffer.append(message)
        for queue in self._subscribers:
            queue.put_nowait(message)

    def subscribe(self) -> asyncio.Queue[BaseWSMessage]:
        if len(self._subscribers) >= MAX_CONNECTIONS_PER_SESSION:
            raise TooManyConnectionsError(
                f"Session {self.session_id!r} already has {MAX_CONNECTIONS_PER_SESSION} "
                "live WebSocket connections."
            )
        queue: asyncio.Queue[BaseWSMessage] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[BaseWSMessage]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def replay(self) -> list[BaseWSMessage]:
        """Every message emitted so far, oldest first — what a
        reconnecting or mid-run client receives before switching to
        live delivery from its own subscribed queue."""
        return list(self._buffer)
