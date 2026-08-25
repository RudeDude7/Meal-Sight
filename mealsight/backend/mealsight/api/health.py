"""Health-check logic for GET /health: three independent checks —
each MCP server (reachable, and reporting its expected tool count),
each LLM provider (a cheap, real reachability probe against its own
models-list endpoint — no completion, no token cost), and the recipe
database (population, checked through recipe_engine's own
search_recipes rather than any direct DB access, matching this whole
API's "no direct database access from the API layer" rule).

Provider reachability is cached briefly (HEALTH_CACHE_SECONDS) rather
than probed on every single /health hit: a load balancer or uptime
monitor polling this endpoint every few seconds would otherwise turn
into a steady drip of real outbound calls to Mistral/Groq for no real
benefit — reachability doesn't change that fast, and the cache is
per-provider, so one being briefly slow to answer doesn't block
reporting on the other three checks.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from mealsight.agent.mcp_client import EXPECTED_TOOLS, MCPClientManager
from mealsight.config.settings import settings
from mealsight.providers.groq import BASE_URL as GROQ_BASE_URL
from mealsight.providers.mistral import BASE_URL as MISTRAL_BASE_URL
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.api.health")

HEALTH_CACHE_SECONDS = 30.0
PROBE_TIMEOUT_SECONDS = 3.0

_provider_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def reset_provider_cache() -> None:
    """Test-only: clears the reachability cache so a test can force a
    fresh probe instead of reusing another test's cached result."""
    _provider_cache.clear()


async def _check_mcp_servers(manager: MCPClientManager) -> dict[str, Any]:
    try:
        inventory = await manager.list_tool_inventory()
    except Exception as exc:
        logger.error("health_mcp_inventory_failed", exc_info=True)
        return {name: {"status": "down", "detail": str(exc)} for name in EXPECTED_TOOLS}

    result: dict[str, Any] = {}
    for name, expected_tools in EXPECTED_TOOLS.items():
        found = set(inventory.get(name, []))
        missing = expected_tools - found
        result[name] = {
            "status": "up" if not missing else "down",
            "tool_count": len(found),
            **({"missing_tools": sorted(missing)} if missing else {}),
        }
    return result


async def _probe_provider(
    client: httpx.AsyncClient, name: str, url: str, headers: dict[str, str]
) -> dict[str, Any]:
    cached = _provider_cache.get(name)
    if cached is not None and (time.monotonic() - cached[0]) < HEALTH_CACHE_SECONDS:
        return cached[1]

    try:
        response = await client.get(url, headers=headers, timeout=PROBE_TIMEOUT_SECONDS)
        status_result = {"status": "up" if response.status_code < 500 else "down"}
    except Exception as exc:
        status_result = {"status": "down", "detail": str(exc)}

    _provider_cache[name] = (time.monotonic(), status_result)
    return status_result


async def _check_providers(client: httpx.AsyncClient) -> dict[str, Any]:
    mistral_result, groq_result = await asyncio.gather(
        _probe_provider(
            client, "mistral", f"{MISTRAL_BASE_URL}/models",
            {"Authorization": f"Bearer {settings.mistral_api_key.get_secret_value()}"},
        ),
        _probe_provider(
            client, "groq", f"{GROQ_BASE_URL}/models",
            {"Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}"},
        ),
    )
    return {"mistral": mistral_result, "groq": groq_result}


async def _check_recipe_database(manager: MCPClientManager) -> dict[str, Any]:
    result = await manager.call_tool("recipe_engine", "search_recipes", {"max_results": 1})
    if not result.success or not isinstance(result.data, dict):
        return {"status": "down", "detail": result.error or "search_recipes call failed"}

    total = result.data.get("total_matched", 0)
    return {"status": "up" if total > 0 else "down", "recipe_count": total}


async def build_health_report(manager: MCPClientManager, http_client: httpx.AsyncClient) -> dict[str, Any]:
    mcp_servers, providers, recipe_database = await asyncio.gather(
        _check_mcp_servers(manager),
        _check_providers(http_client),
        _check_recipe_database(manager),
    )

    all_ok = (
        all(server["status"] == "up" for server in mcp_servers.values())
        and all(provider["status"] == "up" for provider in providers.values())
        and recipe_database["status"] == "up"
    )

    return {
        "status": "healthy" if all_ok else "degraded",
        "mcp_servers": mcp_servers,
        "providers": providers,
        "recipe_database": recipe_database,
    }

