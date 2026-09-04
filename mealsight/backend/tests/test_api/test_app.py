"""Tests for mealsight.api against a real FastAPI app + httpx.AsyncClient
(ASGI transport, no real network) — but a FAKE MCPClientManager and a
FAKE health-check http client, the exact same "no real MCP servers or
providers" convention mealsight.agent's own node tests already use
(FakeMCP in tests/test_agent/test_nodes.py). run_recommendation itself
is monkeypatched for these tests too: exercising the real agent graph
belongs to tests/test_agent, not here — this file tests the API layer's
OWN behavior (status codes, session polling, validation, rate limiting,
proxying, error shape), not agent correctness.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

from mealsight.agent.mcp_client import ToolCallResult
from mealsight.api.app import create_app
from mealsight.api.health import reset_provider_cache
from mealsight.api.idempotency import IdempotencyStore
from mealsight.api.rate_limit import SubmissionRateLimiter
from mealsight.api.sessions import SessionStore


@pytest.fixture(autouse=True)
def _reset_health_cache() -> None:
    # mealsight.api.health's own reachability cache is a module-level
    # dict, deliberately shared across real requests within one running
    # process — but that means it's also shared across TESTS in this
    # same pytest process unless reset, which would let one test's
    # cached "up" leak into a later test that specifically wants to
    # observe "down".
    reset_provider_cache()

# importlib, not a plain import — matches this project's own established
# reason for it (tests/test_agent/test_nodes.py's own comment): a
# package __init__ re-exporting a submodule's attribute would otherwise
# shadow a plain `import ... as x`, though mealsight.api.routers has no
# such re-export today. Used consistently anyway for monkeypatching the
# actual module object, not whatever name happens to be bound in it.
recommend_module = importlib.import_module("mealsight.api.routers.recommend")

DEFAULT_INVENTORY: dict[str, list[str]] = {
    "recipe_engine": [
        "search_recipes",
        "get_recipe",
        "match_ingredients",
        "scale_recipe",
        "calculate_nutrition",
        "find_substitutions",
        "get_recipe_by_ingredients",
    ],
    "pantry_manager": [
        "update_pantry",
        "get_pantry",
        "remove_items",
        "flag_expiring",
        "create_grocery_list",
        "get_grocery_list",
        "log_waste",
        "get_waste_stats",
    ],
    "user_intelligence": [
        "get_user_profile",
        "update_preferences",
        "remove_preference",
        "log_meal",
        "rate_meal",
        "get_meal_history",
        "check_repetition",
        "get_context_signals",
        "record_interaction",
        "get_interaction_history",
        "get_taste_insights",
    ],
}


class FakeManager:
    """Stands in for MCPClientManager — same shape as tests/test_agent's
    own FakeMCP, plus list_tool_inventory for the health check."""

    def __init__(
        self,
        responses: dict[tuple[str, str], ToolCallResult] | None = None,
        inventory: dict[str, list[str]] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._inventory = inventory if inventory is not None else DEFAULT_INVENTORY
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_tool(
        self, server: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        self.calls.append((server, tool_name, arguments or {}))
        return self._responses.get((server, tool_name), ToolCallResult(success=False, error="unconfigured"))

    async def list_tool_inventory(self) -> dict[str, list[str]]:
        return self._inventory


class FakeHealthHttpClient:
    """Stands in for the health check's own httpx.AsyncClient — no real
    network call to Mistral/Groq."""

    def __init__(self, status_code: int = 200) -> None:
        self._status_code = status_code

    async def get(
        self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> httpx.Response:
        return httpx.Response(self._status_code, request=httpx.Request("GET", url))


def _lifespan_with(
    manager: FakeManager, rate_limit: int = 100, http_status: int = 200
) -> Any:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.mcp_manager = manager
        app.state.sessions = SessionStore()
        app.state.rate_limiter = SubmissionRateLimiter(limit=rate_limit)
        app.state.health_http_client = FakeHealthHttpClient(status_code=http_status)
        app.state.idempotency_store = IdempotencyStore()
        yield

    return lifespan


@asynccontextmanager
async def running_client(
    manager: FakeManager | None = None, rate_limit: int = 100, http_status: int = 200
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeManager]]:
    manager = manager or FakeManager()
    lifespan_override = _lifespan_with(manager, rate_limit=rate_limit, http_status=http_status)
    app = create_app(lifespan_override=lifespan_override)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client, manager


def _tiny_png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (200, 200), color=(200, 100, 50)).save(buffer, format="PNG")
    return buffer.getvalue()


def _search_recipes_ok(total_matched: int = 250) -> ToolCallResult:
    return ToolCallResult(success=True, data={"results": [], "total_matched": total_matched})


# --------------------------------------------------------------------
# /health
# --------------------------------------------------------------------


async def test_health_reports_all_servers() -> None:
    manager = FakeManager(responses={("recipe_engine", "search_recipes"): _search_recipes_ok()})
    async with running_client(manager) as (client, _manager):
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["mcp_servers"]["recipe_engine"] == {"status": "up", "tool_count": 7}
    assert body["mcp_servers"]["pantry_manager"]["status"] == "up"
    assert body["mcp_servers"]["user_intelligence"]["status"] == "up"
    assert body["providers"]["mistral"]["status"] == "up"
    assert body["providers"]["groq"]["status"] == "up"
    assert body["recipe_database"] == {"status": "up", "recipe_count": 250}


async def test_health_returns_503_when_a_server_is_missing_tools() -> None:
    incomplete_inventory = {**DEFAULT_INVENTORY, "pantry_manager": ["get_pantry"]}
    manager = FakeManager(
        responses={("recipe_engine", "search_recipes"): _search_recipes_ok()},
        inventory=incomplete_inventory,
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["mcp_servers"]["pantry_manager"]["status"] == "down"


async def test_health_returns_503_when_a_provider_is_unreachable() -> None:
    manager = FakeManager(responses={("recipe_engine", "search_recipes"): _search_recipes_ok()})
    async with running_client(manager, http_status=500) as (client, _manager):
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["providers"]["mistral"]["status"] == "down"


# --------------------------------------------------------------------
# POST /api/recommend, GET /api/recommend/{session_id}
# --------------------------------------------------------------------


async def test_recommend_accepts_multipart_and_returns_202_with_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_recommendation(**kwargs: Any) -> dict[str, Any]:
        return {"final_response": "Fake recipe response", "stream_messages": ["done"]}

    monkeypatch.setattr(recommend_module, "run_recommendation", fake_run_recommendation)

    async with running_client() as (client, _manager):
        response = await client.post(
            "/api/recommend",
            data={"text": "something quick and vegetarian"},
            files={"image": ("photo.png", _tiny_png_bytes(), "image/png")},
        )

    assert response.status_code == 202
    body = response.json()
    assert "session_id" in body
    assert body["status"] == "pending"
    assert body["websocket_url"] == f"/ws/{body['session_id']}"


async def test_recommend_polling_returns_pending_then_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow_fake_run_recommendation(**kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(0.1)
        return {"final_response": "Fake recipe response", "stream_messages": ["done"]}

    monkeypatch.setattr(recommend_module, "run_recommendation", slow_fake_run_recommendation)

    async with running_client() as (client, _manager):
        start_response = await client.post("/api/recommend", data={"text": "anything quick"})
        session_id = start_response.json()["session_id"]

        immediate_poll = await client.get(f"/api/recommend/{session_id}")
        assert immediate_poll.json()["status"] in {"pending", "running"}

        await asyncio.sleep(0.25)

        final_poll = await client.get(f"/api/recommend/{session_id}")
        final_body = final_poll.json()
        assert final_body["status"] == "complete"
        assert final_body["result"]["final_response"] == "Fake recipe response"


async def test_recommend_zero_modalities_returns_400() -> None:
    async with running_client() as (client, _manager):
        response = await client.post("/api/recommend", data={})

    assert response.status_code == 400
    assert response.json()["code"] == "no_input_provided"


async def test_recommend_unknown_session_returns_404() -> None:
    async with running_client() as (client, _manager):
        response = await client.get("/api/recommend/does-not-exist")

    assert response.status_code == 404


def test_reject_oversized_rejects_before_reading_body() -> None:
    from mealsight.api.errors import APIError
    from mealsight.api.routers.recommend import MAX_REQUEST_BYTES, _reject_oversized

    class FakeRequest:
        headers = {"content-length": str(MAX_REQUEST_BYTES + 1)}

    with pytest.raises(APIError) as exc_info:
        _reject_oversized(FakeRequest())  # type: ignore[arg-type]
    assert exc_info.value.status_code == 413


async def test_rate_limit_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_recommendation(**kwargs: Any) -> dict[str, Any]:
        return {"final_response": "ok", "stream_messages": []}

    monkeypatch.setattr(recommend_module, "run_recommendation", fake_run_recommendation)

    async with running_client(rate_limit=1) as (client, _manager):
        first = await client.post("/api/recommend", data={"text": "first request"})
        second = await client.post("/api/recommend", data={"text": "second request"})

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limited"


# --------------------------------------------------------------------
# proxy endpoints
# --------------------------------------------------------------------


async def test_pantry_get_proxies_mcp_data() -> None:
    manager = FakeManager(
        responses={
            ("pantry_manager", "get_pantry"): ToolCallResult(
                success=True, data={"items": [{"id": 1, "name": "onion"}], "count": 1}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/pantry")

    assert response.status_code == 200
    assert response.json() == {"items": [{"id": 1, "name": "onion"}], "count": 1}


async def test_pantry_delete_resolves_id_then_removes() -> None:
    manager = FakeManager(
        responses={
            ("pantry_manager", "get_pantry"): ToolCallResult(
                success=True, data={"items": [{"id": 7, "name": "garlic", "quantity": 3.0}], "count": 1}
            ),
            ("pantry_manager", "remove_items"): ToolCallResult(
                success=True, data={"details": [{"name": "garlic", "found": True, "deleted": True}]}
            ),
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.delete("/api/pantry/7")

    assert response.status_code == 200
    remove_call = next(args for _, tool, args in manager.calls if tool == "remove_items")
    assert remove_call["items"] == [{"name": "garlic", "quantity_used": 3.0}]


async def test_recipes_get_by_id_proxies_mcp_data() -> None:
    manager = FakeManager(
        responses={
            ("recipe_engine", "get_recipe"): ToolCallResult(success=True, data={"id": "52958", "name": "PBC"})
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/recipes/52958")

    assert response.status_code == 200
    assert response.json()["name"] == "PBC"


async def test_recipes_by_ingredients_proxies_mcp_data_and_is_matched_before_the_id_route() -> None:
    manager = FakeManager(
        responses={
            ("recipe_engine", "get_recipe_by_ingredients"): ToolCallResult(
                success=True, data={"results": [{"id": "1", "match_percentage": 1.0}], "total_matched": 1}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get(
            "/api/recipes/by-ingredients", params={"ingredients": ["egg", "flour"]}
        )

    assert response.status_code == 200
    assert response.json()["total_matched"] == 1
    call_args = next(
        args for _, tool, args in manager.calls if tool == "get_recipe_by_ingredients"
    )
    assert call_args["ingredients"] == ["egg", "flour"]
    assert call_args["minimum_match_percentage"] == 0.6


async def test_insights_get_proxies_mcp_data() -> None:
    manager = FakeManager(
        responses={
            ("user_intelligence", "get_taste_insights"): ToolCallResult(
                success=True, data={"time_range": "this_month", "sufficient_history": False}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/insights", params={"time_range": "this_month"})

    assert response.status_code == 200
    assert response.json()["sufficient_history"] is False


async def test_history_proxies_mcp_data() -> None:
    manager = FakeManager(
        responses={
            ("user_intelligence", "get_meal_history"): ToolCallResult(
                success=True, data={"meals": [], "count": 0}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/history")

    assert response.status_code == 200
    assert response.json() == {"meals": [], "count": 0}


async def test_profile_get_proxies_mcp_data() -> None:
    manager = FakeManager(
        responses={
            ("user_intelligence", "get_user_profile"): ToolCallResult(
                success=True, data={"household_size": 2}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/profile")

    assert response.status_code == 200
    assert response.json() == {"household_size": 2}


async def test_grocery_list_proxies_mcp_data() -> None:
    manager = FakeManager(
        responses={
            ("pantry_manager", "get_grocery_list"): ToolCallResult(
                success=True, data={"id": 1, "sections": []}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/grocery-list")

    assert response.status_code == 200
    assert response.json() == {"id": 1, "sections": []}


async def test_waste_post_proxies_mcp_data() -> None:
    manager = FakeManager(
        responses={
            ("pantry_manager", "log_waste"): ToolCallResult(
                success=True, data={"id": 1, "item_name": "spinach", "insight": None}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.post(
            "/api/waste",
            json={"item_name": "spinach", "quantity_wasted": 1.0, "unit": "bag", "reason": "expired"},
        )

    assert response.status_code == 200
    assert response.json() == {"id": 1, "item_name": "spinach", "insight": None}
    call_args = next(args for _, tool, args in manager.calls if tool == "log_waste")
    assert call_args == {
        "item_name": "spinach",
        "quantity_wasted": 1.0,
        "unit": "bag",
        "reason": "expired",
    }


async def test_waste_get_proxies_mcp_data() -> None:
    manager = FakeManager(
        responses={
            ("pantry_manager", "get_waste_stats"): ToolCallResult(
                success=True, data={"time_range": "this_week", "total_items_wasted": 0}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/waste", params={"time_range": "this_week"})

    assert response.status_code == 200
    assert response.json() == {"time_range": "this_week", "total_items_wasted": 0}


def _meal_plan_manager(recipe_ids: list[tuple[str, str]]) -> FakeManager:
    return FakeManager(
        responses={
            ("pantry_manager", "get_pantry"): ToolCallResult(success=True, data={"items": [], "count": 0}),
            ("pantry_manager", "flag_expiring"): ToolCallResult(
                success=True, data={"items": [], "count": 0}
            ),
            ("user_intelligence", "get_user_profile"): ToolCallResult(
                success=True, data={"cuisine_preferences": {}}
            ),
            ("recipe_engine", "search_recipes"): ToolCallResult(
                success=True,
                data={
                    "results": [
                        {
                            "id": rid,
                            "name": rid,
                            "cuisine": cuisine,
                            "meal_type": "main",
                            "cook_time_minutes": 30,
                            "dietary_tags": [],
                        }
                        for rid, cuisine in recipe_ids
                    ],
                    "total_matched": len(recipe_ids),
                },
            ),
            ("recipe_engine", "match_ingredients"): ToolCallResult(
                success=True,
                data={
                    "match_score": 0.8,
                    "can_cook": True,
                    "matched_items": [],
                    "substitutable_items": [],
                    "partial_matches": [],
                    "missing_items": [],
                    "critical_missing": [],
                    "summary": "",
                },
            ),
            ("recipe_engine", "get_recipe"): ToolCallResult(
                success=True, data={"servings_base": 2, "ingredients": []}
            ),
            ("recipe_engine", "calculate_nutrition"): ToolCallResult(
                success=True, data={"calories": 400.0}
            ),
            ("user_intelligence", "check_repetition"): ToolCallResult(
                success=True, data={"repetition_score": 0.0, "recommendation": "acceptable"}
            ),
            ("pantry_manager", "create_grocery_list"): ToolCallResult(
                success=True, data={"id": 1, "status": "active", "sections": []}
            ),
        }
    )


async def test_meal_plan_post_returns_a_real_plan() -> None:
    recipe_ids = [(f"r{i}", f"cuisine{i}") for i in range(5)]
    manager = _meal_plan_manager(recipe_ids)

    async with running_client(manager) as (client, _manager):
        response = await client.post("/api/meal-plan", json={"days": 5, "servings": 2})

    assert response.status_code == 200
    body = response.json()
    assert len(body["days"]) == 5
    assert "grocery_list" in body
    assert "total_distinct_ingredients" in body


async def test_meal_plan_post_unsatisfiable_constraints_becomes_422() -> None:
    recipe_ids = [("r0", "italian"), ("r1", "mexican")]
    manager = _meal_plan_manager(recipe_ids)

    async with running_client(manager) as (client, _manager):
        response = await client.post("/api/meal-plan", json={"days": 5, "servings": 2})

    assert response.status_code == 422
    assert response.json()["code"] == "plan_unsatisfiable"


async def test_waste_get_validation_error_becomes_400() -> None:
    manager = FakeManager(
        responses={
            ("pantry_manager", "get_waste_stats"): ToolCallResult(
                success=True,
                data={"error": "validation_error", "parameter": "time_range", "message": "bad range"},
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/waste", params={"time_range": "bogus"})

    assert response.status_code == 400


# --------------------------------------------------------------------
# cross-cutting: trace id header, error envelope
# --------------------------------------------------------------------


async def test_trace_id_header_present_on_every_response() -> None:
    manager = FakeManager(responses={("recipe_engine", "search_recipes"): _search_recipes_ok()})
    async with running_client(manager) as (client, _manager):
        response = await client.get("/health")

    assert "x-trace-id" in response.headers
    assert len(response.headers["x-trace-id"]) > 0


async def test_error_envelope_shape_is_consistent() -> None:
    manager = FakeManager(
        responses={
            ("recipe_engine", "get_recipe"): ToolCallResult(
                success=True, data={"error": "not_found", "message": "No recipe found.", "recipe_id": "x"}
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/recipes/x")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "trace_id"}
    assert body["code"] == "not_found"
