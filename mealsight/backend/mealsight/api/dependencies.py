"""FastAPI dependency accessors for everything mealsight.api.app's own
lifespan puts on app.state: the one process-lifetime MCPClientManager,
the recommendation SessionStore, and the submission rate limiter.
Routers depend on these rather than importing app.state directly, so a
route function's own signature says exactly what it needs and stays
trivially testable with a fake Request/app.state in isolation.
"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import Depends, Request, WebSocket

from mealsight.agent.mcp_client import MCPClientManager
from mealsight.api.rate_limit import SubmissionRateLimiter
from mealsight.api.sessions import SessionStore


def get_mcp_manager(request: Request) -> MCPClientManager:
    return request.app.state.mcp_manager  # type: ignore[no-any-return]


def get_sessions(request: Request) -> SessionStore:
    return request.app.state.sessions  # type: ignore[no-any-return]


def get_rate_limiter(request: Request) -> SubmissionRateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


def get_health_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.health_http_client  # type: ignore[no-any-return]


# WebSocket routes receive a WebSocket, never a Request — both are
# starlette.requests.HTTPConnection subclasses with an identical
# `.app.state`, but FastAPI resolves a dependency's own declared
# parameter type, so a Request-typed getter silently never fires for a
# websocket route. A second, tiny getter per shared piece of state is
# the plain, explicit fix — no cleverness, just the right parameter type
# for the route kind that actually uses it.
def get_sessions_ws(websocket: WebSocket) -> SessionStore:
    return websocket.app.state.sessions  # type: ignore[no-any-return]


# Annotated[..., Depends(...)] aliases — FastAPI's own recommended
# dependency-injection style, used in every router's own signature
# instead of a `= Depends(...)` default value. Beyond being the more
# current idiom, it also sidesteps flake8-bugbear's B008 ("no function
# calls in argument defaults"), which doesn't special-case FastAPI's
# own Depends() pattern — the alias moves the call out of a default
# value entirely rather than suppressing the rule project-wide.
MCPManagerDep = Annotated[MCPClientManager, Depends(get_mcp_manager)]
SessionsDep = Annotated[SessionStore, Depends(get_sessions)]
RateLimiterDep = Annotated[SubmissionRateLimiter, Depends(get_rate_limiter)]
HealthHttpClientDep = Annotated[httpx.AsyncClient, Depends(get_health_http_client)]
SessionsWSDep = Annotated[SessionStore, Depends(get_sessions_ws)]
