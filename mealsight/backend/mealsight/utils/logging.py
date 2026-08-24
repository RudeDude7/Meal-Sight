"""Structured logging for the MealSight backend.

`get_logger(name)` is the only entry point application code should use.
Every emitted event carries `timestamp`, `level`, `service` (the `name`
passed to `get_logger`), and `event` (the log message) — plus, if one has
been bound in the current context, `trace_id`.

Trace propagation uses `contextvars` rather than threading an id through
every function signature: `bind_trace_id` sets it once per request/task,
and a structlog processor injects it into every subsequent log line in
that context — including across `await` boundaries, since a contextvar's
value is part of the asyncio Task's copied context.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

from mealsight.config.settings import settings

_trace_id_var: ContextVar[str | None] = ContextVar("mealsight_trace_id", default=None)


def bind_trace_id(trace_id: str) -> None:
    """Binds a trace id to the current context (coroutine/task or thread).

    Every log line emitted from this point on, in this context — including
    after `await`ing into other coroutines spawned from here — will carry
    `trace_id` automatically.
    """
    _trace_id_var.set(trace_id)


def current_trace_id() -> str | None:
    return _trace_id_var.get()


def _inject_trace_id(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    trace_id = _trace_id_var.get()
    if trace_id is not None:
        event_dict["trace_id"] = trace_id
    return event_dict


def configure_logging(environment: str) -> None:
    """(Re)configures structlog for the given environment. Safe to call
    more than once — `get_logger` calls this on every invocation so tests
    can flip `environment` and see it take effect immediately."""
    shared_processors: list[Any] = [
        structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
        structlog.stdlib.add_log_level,
        _inject_trace_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if environment == "production":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        # file=sys.stderr, not the default stdout: the recipe-engine MCP
        # server (mealsight.mcp_servers.recipe_engine) speaks the MCP
        # protocol over stdio, so anything writing to stdout — including
        # a stray log line — would corrupt that stream. Diagnostics
        # belong on stderr regardless of transport; this was never
        # correct to leave on stdout even before the MCP server existed.
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> Any:
    """Returns a structlog logger bound with `service=name`.

    Reconfigures structlog for the current `settings.environment` first —
    cheap enough to do on every call, and it's what makes switching
    environments (e.g. in tests) actually take effect.
    """
    configure_logging(settings.environment)
    return structlog.get_logger().bind(service=name)


@contextmanager
def timed_block(logger: Any, event: str, **extra: Any) -> Iterator[None]:
    """Times the wrapped block and logs `event` with `duration_ms` on exit,
    even if the block raises."""
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(event, duration_ms=duration_ms, **extra)
