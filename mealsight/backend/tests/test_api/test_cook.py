"""Tests for POST /api/cook and POST /api/history/{meal_id}/rate — the
cook-confirmation flow. Same FakeManager/running_client convention as
tests/test_api/test_app.py: a fake MCPClientManager, real FastAPI app,
real ASGI transport, no real MCP subprocesses.
"""

from __future__ import annotations

from mealsight.agent.mcp_client import ToolCallResult
from tests.test_api.test_app import FakeManager, running_client

RECIPE_DATA = {
    "id": "recipe-1",
    "name": "Udon Noodle Soup",
    "cuisine": "japanese",
    "meal_type": "dinner",
    "servings_base": 2,
    "ingredients": [
        {"name": "Udon Noodles", "quantity": 200.0, "unit": "g"},
        {"name": "Soy Sauce", "quantity": 30.0, "unit": "ml"},
        {"name": "Mystery Spice", "quantity": None, "unit": "tsp"},
        {"name": "Chili Oil", "quantity": 10.0, "unit": "ml"},
    ],
}

PANTRY_DATA = {
    "items": [
        {"id": 1, "name": "udon noodles", "quantity": 500.0, "unit": "g"},
        {"id": 2, "name": "soy sauce", "quantity": 100.0, "unit": "ml"},
        {"id": 3, "name": "mystery spice", "quantity": 20.0, "unit": "tsp"},
    ]
}

MATCH_DATA = {
    "match_score": 1.0,
    "can_cook": True,
    "matched_items": [
        {"name": "Udon Noodles", "importance": "critical"},
        {"name": "Soy Sauce", "importance": "optional"},
    ],
    "substitutable_items": [],
    "partial_matches": [],
    "missing_items": [],
    "critical_missing": [],
    "summary": "ok",
}

MEAL_RECORD = {
    "id": 42,
    "recipe_id": "recipe-1",
    "recipe_name": "Udon Noodle Soup",
    "cuisine": "japanese",
    "meal_type": "dinner",
    "date": "2026-08-25",
    "rating": None,
    "servings_made": 2,
    "ingredients_used": None,
    "notes": None,
    "cooked_at": "2026-08-25T00:00:00",
}

REMOVAL_DATA = {
    "details": [
        {
            "name": "Udon Noodles",
            "canonical_name": "udon noodles",
            "found": True,
            "quantity_requested": 200.0,
            "quantity_removed": 200.0,
            "quantity_remaining": 300.0,
            "discrepancy": 0.0,
            "deleted": False,
        },
        {
            "name": "Soy Sauce",
            "canonical_name": "soy sauce",
            "found": True,
            "quantity_requested": 30.0,
            "quantity_removed": 30.0,
            "quantity_remaining": 70.0,
            "discrepancy": 0.0,
            "deleted": False,
        },
    ]
}

PROFILE_DATA = {
    "dietary_restrictions": [],
    "disliked_ingredients": [],
    "preferred_cook_time_minutes": None,
    "household_size": None,
    "protein_preference": None,
    "cooking_skill": None,
    "budget_sensitivity": None,
    "cuisine_preferences": {"japanese": 0.5},
}

PROFILE_DATA_AFTER = {**PROFILE_DATA, "cuisine_preferences": {"japanese": 0.75}}


def _base_manager(rating: int | None = None) -> FakeManager:
    meal = {**MEAL_RECORD, "rating": rating}
    responses: dict[tuple[str, str], ToolCallResult] = {
        ("recipe_engine", "get_recipe"): ToolCallResult(success=True, data=RECIPE_DATA),
        ("user_intelligence", "log_meal"): ToolCallResult(success=True, data=meal),
        ("user_intelligence", "get_user_profile"): ToolCallResult(success=True, data=PROFILE_DATA),
        ("pantry_manager", "get_pantry"): ToolCallResult(success=True, data=PANTRY_DATA),
        ("recipe_engine", "match_ingredients"): ToolCallResult(success=True, data=MATCH_DATA),
        ("pantry_manager", "remove_items"): ToolCallResult(success=True, data=REMOVAL_DATA),
    }
    return FakeManager(responses)


async def test_cook_logs_meal_and_deducts_pantry() -> None:
    manager = _base_manager()
    async with running_client(manager) as (client, _manager):
        response = await client.post(
            "/api/cook", json={"recipe_id": "recipe-1", "servings_made": 2}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["meal"]["id"] == 42
    assert body["pantry_deduction_error"] is None
    assert {d["name"]: d for d in body["deducted"]}["Udon Noodles"] == {
        "name": "Udon Noodles",
        "before": 500.0,
        "after": 300.0,
        "quantity_removed": 200.0,
    }
    assert any(s["reason"] == "quantity_unknown" for s in body["skipped"]) is False
    assert manager.calls[0] == ("recipe_engine", "get_recipe", {"recipe_id": "recipe-1"})
    assert manager.calls[1] == ("user_intelligence", "log_meal", manager.calls[1][2])


async def test_repeat_call_with_same_idempotency_key_does_not_double_deduct() -> None:
    manager = _base_manager()
    async with running_client(manager) as (client, _manager):
        body_payload = {
            "recipe_id": "recipe-1",
            "servings_made": 2,
            "idempotency_key": "click-1",
        }
        first = await client.post("/api/cook", json=body_payload)
        second = await client.post("/api/cook", json=body_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["meal"] == second.json()["meal"]
    assert first.json()["idempotent_replay"] is False
    assert second.json()["idempotent_replay"] is True
    remove_calls = [c for c in manager.calls if c[:2] == ("pantry_manager", "remove_items")]
    assert len(remove_calls) == 1


async def test_ingredients_not_in_pantry_are_skipped_not_erroring() -> None:
    manager = _base_manager()
    async with running_client(manager) as (client, _manager):
        response = await client.post(
            "/api/cook",
            json={
                "recipe_id": "recipe-1",
                "servings_made": 2,
                "ingredients_used": ["Udon Noodles", "Chili Oil"],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["pantry_deduction_error"] is None
    assert {"name": "Chili Oil", "reason": "not_in_pantry"} in body["skipped"]


async def test_ingredient_not_in_recipe_is_skipped() -> None:
    manager = _base_manager()
    async with running_client(manager) as (client, _manager):
        response = await client.post(
            "/api/cook",
            json={
                "recipe_id": "recipe-1",
                "servings_made": 2,
                "ingredients_used": ["Udon Noodles", "Mystery Spice"],
            },
        )
    assert response.status_code == 200
    body = response.json()
    skipped_reasons = {s["name"]: s["reason"] for s in body["skipped"]}
    assert skipped_reasons["Mystery Spice"] == "quantity_unknown"


async def test_rating_flows_through_log_meal_and_updates_preferences() -> None:
    manager = _base_manager(rating=5)
    manager._responses[("user_intelligence", "get_user_profile")] = ToolCallResult(
        success=True, data=PROFILE_DATA
    )
    async with running_client(manager) as (client, _manager):
        response = await client.post(
            "/api/cook", json={"recipe_id": "recipe-1", "servings_made": 2, "rating": 5}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["meal"]["rating"] == 5
    log_meal_call = next(c for c in manager.calls if c[:2] == ("user_intelligence", "log_meal"))
    assert log_meal_call[2]["rating"] == 5
    assert body["preferences_before"] is not None
    assert body["preferences_after"] is not None


async def test_deduction_never_exceeds_pantry_holdings() -> None:
    manager = _base_manager()
    clamped_removal = {
        "details": [
            {
                "name": "Udon Noodles",
                "canonical_name": "udon noodles",
                "found": True,
                "quantity_requested": 200.0,
                "quantity_removed": 500.0,
                "quantity_remaining": 0.0,
                "discrepancy": 0.0,
                "deleted": True,
            }
        ]
    }
    manager._responses[("pantry_manager", "remove_items")] = ToolCallResult(
        success=True, data=clamped_removal
    )
    async with running_client(manager) as (client, _manager):
        response = await client.post(
            "/api/cook",
            json={"recipe_id": "recipe-1", "servings_made": 2, "ingredients_used": ["Udon Noodles"]},
        )
    body = response.json()
    deducted = body["deducted"][0]
    assert deducted["after"] == 0.0
    assert deducted["after"] >= 0.0
    assert deducted["quantity_removed"] <= deducted["before"]


async def test_rating_endpoint_updates_scores() -> None:
    responses: dict[tuple[str, str], ToolCallResult] = {
        ("user_intelligence", "rate_meal"): ToolCallResult(
            success=True, data={**MEAL_RECORD, "rating": 4}
        ),
        ("user_intelligence", "get_user_profile"): ToolCallResult(
            success=True, data=PROFILE_DATA_AFTER
        ),
    }
    manager = FakeManager(responses)
    async with running_client(manager) as (client, _manager):
        response = await client.post("/api/history/42/rate", json={"rating": 4})
    assert response.status_code == 200
    body = response.json()
    assert body["meal"]["rating"] == 4
    assert body["cuisine_preferences"] == {"japanese": 0.75}


async def test_rating_unknown_meal_id_errors_cleanly() -> None:
    responses: dict[tuple[str, str], ToolCallResult] = {
        ("user_intelligence", "rate_meal"): ToolCallResult(
            success=True, data={"error": "not_found", "message": "No meal found with id 999."}
        ),
    }
    manager = FakeManager(responses)
    async with running_client(manager) as (client, _manager):
        response = await client.post("/api/history/999/rate", json={"rating": 4})
    assert response.status_code == 404


async def test_rating_out_of_range_is_rejected() -> None:
    manager = FakeManager({})
    async with running_client(manager) as (client, _manager):
        response = await client.post("/api/history/42/rate", json={"rating": 7})
    assert response.status_code == 422


async def test_pantry_failure_after_log_meal_still_returns_200() -> None:
    manager = _base_manager()
    manager._responses[("pantry_manager", "get_pantry")] = ToolCallResult(
        success=False, error="transport failure"
    )
    async with running_client(manager) as (client, _manager):
        response = await client.post(
            "/api/cook", json={"recipe_id": "recipe-1", "servings_made": 2}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["meal"]["id"] == 42
    assert body["pantry_deduction_error"] is not None
    assert body["deducted"] == []
