"""create_app — the FastAPI application factory.

THE KEY CHANGE this phase makes: MCPClientManager used to start and
stop once PER RECOMMENDATION (mealsight.agent.runner's own `async with
MCPClientManager()` block) — three subprocess launches plus a health
check on every single run, ~13s of a real ~19.4s recommendation before
this existed. This app's own lifespan starts ONE MCPClientManager when
the process starts, holds it in app.state for the whole process
lifetime, and every request handler (mealsight.api.dependencies.
get_mcp_manager) reuses that same instance — subprocess startup cost is
now paid once per process, not once per request. mealsight.agent.
runner.run_recommendation was extended (not replaced) with an optional
`manager` parameter specifically so this app can hand it the shared
manager while every script and test that calls it directly keeps
working exactly as before, unchanged.

CONCURRENCY: recommendations are NOT serialized behind a lock on the
shared manager. This was a real decision, not an assumption — verified
directly (20 concurrent call_tool invocations issued at once against a
single real MCPClientManager, every one of them returning the correct,
correctly-matched data, no cross-talk) before deciding: the underlying
transport (fastmcp's Client over one stdio session per server) already
multiplexes concurrent requests by their own JSON-RPC id, and every MCP
tool in this project is itself stateless per call (each one reads/
writes its own SQLite database fresh, no server-side per-connection
state a second, concurrent caller could corrupt). A lock would only
trade away real concurrency for a safety property this system already
has for other reasons.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from mealsight.agent.mcp_client import MCPClientManager
from mealsight.api.errors import register_error_handlers
from mealsight.api.idempotency import IdempotencyStore
from mealsight.api.rate_limit import SubmissionRateLimiter
from mealsight.api.routers import (
    cook,
    grocery,
    health,
    history,
    insights,
    interactions,
    meal_plan,
    pantry,
    profile,
    recipes,
    recommend,
    waste,
    ws,
)
from mealsight.api.sessions import SessionStore
from mealsight.config.settings import settings
from mealsight.utils.logging import bind_trace_id, current_trace_id, get_logger

logger = get_logger("mealsight.api.app")

TRACE_ID_HEADER = "X-Trace-Id"

# "Clean up session state after a timeout" — a session (and its
# SessionStream's own buffered messages) is purged this long after
# creation, whether or not anyone ever polled or connected for it.
# Swept periodically rather than on a per-session timer, since an
# in-process dict this small doesn't need one timer per entry.
SESSION_TTL_SECONDS = 3600.0
SESSION_SWEEP_INTERVAL_SECONDS = 60.0


async def _sweep_sessions_periodically(sessions: SessionStore, idempotency: IdempotencyStore) -> None:
    while True:
        await asyncio.sleep(SESSION_SWEEP_INTERVAL_SECONDS)
        removed = sessions.sweep_expired(SESSION_TTL_SECONDS)
        if removed:
            logger.info("sessions_swept", removed=removed)
        removed_keys = idempotency.sweep_expired()
        if removed_keys:
            logger.info("idempotency_keys_swept", removed=removed_keys)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    manager = MCPClientManager()
    await manager.start()
    app.state.mcp_manager = manager
    app.state.sessions = SessionStore()
    app.state.rate_limiter = SubmissionRateLimiter()
    app.state.health_http_client = httpx.AsyncClient()
    app.state.idempotency_store = IdempotencyStore()
    sweep_task = asyncio.create_task(
        _sweep_sessions_periodically(app.state.sessions, app.state.idempotency_store)
    )
    logger.info("api_started")
    try:
        yield
    finally:
        sweep_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweep_task
        await manager.shutdown()
        await app.state.health_http_client.aclose()
        logger.info("api_stopped")


def create_app(
    *, lifespan_override: Callable[[FastAPI], Any] | None = None
) -> FastAPI:
    """lifespan_override exists solely for tests: the real lifespan
    starts three genuine subprocesses, which is correct for a real
    process but far too slow (and far too real) for a unit test — tests
    substitute their own lifespan that puts a FakeMCP-style stand-in on
    app.state.mcp_manager instead, exactly the same pattern mealsight.
    agent's own node tests already use for MCPClientManager itself.
    """
    app = FastAPI(title="MealSight API", lifespan=lifespan_override or lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[TRACE_ID_HEADER],
    )

    @app.middleware("http")
    async def _bind_trace_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get(TRACE_ID_HEADER) or str(uuid.uuid4())
        bind_trace_id(trace_id)
        response = await call_next(request)
        response.headers[TRACE_ID_HEADER] = current_trace_id() or trace_id
        return response

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(recommend.router)
    app.include_router(cook.router)
    app.include_router(pantry.router)
    app.include_router(recipes.router)
    app.include_router(history.router)
    app.include_router(interactions.router)
    app.include_router(profile.router)
    app.include_router(grocery.router)
    app.include_router(waste.router)
    app.include_router(meal_plan.router)
    app.include_router(insights.router)
    app.include_router(ws.router)

    return app


app = create_app()
