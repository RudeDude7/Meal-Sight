"""GET /health — reports API status, each MCP server (up/down plus its
tool count), each LLM provider's real reachability, and recipe database
population. Returns 503 with the same body when anything is down, so a
caller doesn't have to parse a 200 response body to find out something
is actually broken.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from mealsight.api.dependencies import HealthHttpClientDep, MCPManagerDep
from mealsight.api.health import build_health_report

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    response: Response,
    manager: MCPManagerDep,
    http_client: HealthHttpClientDep,
) -> dict[str, Any]:
    report = await build_health_report(manager, http_client)
    if report["status"] != "healthy":
        response.status_code = 503
    return report
