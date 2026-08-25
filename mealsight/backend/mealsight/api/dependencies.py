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
from fastapi import Depends, Request

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
