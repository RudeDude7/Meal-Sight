"""Tests for the user-intelligence MCP tools' actual behavior, called
through the real FastMCP in-memory client."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastmcp import Client

from tests.test_mcp_servers.test_user_intelligence.conftest import insert_recipe


async def test_get_user_profile_happy_path_on_a_fresh_database(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool("get_user_profile", {})

    assert result.data["dietary_restrictions"] == []
    assert result.data["household_size"] >= 1
    assert result.data["cuisine_preferences"] == {}


async def test_update_preferences_happy_path(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool(
        "update_preferences", {"preference_type": "dietary_restrictions", "value": "vegan"}
    )

    assert result.data["dietary_restrictions"] == ["vegan"]


async def test_update_preferences_invalid_preference_type_returns_validation_error(
    mcp_client: Client[Any],
) -> None:
    result = await mcp_client.call_tool(
        "update_preferences", {"preference_type": "favorite_color", "value": "blue"}
    )

    assert result.data["error"] == "validation_error"
    assert result.data["parameter"] == "favorite_color"


async def test_update_preferences_out_of_range_value_returns_validation_error(
    mcp_client: Client[Any],
) -> None:
    result = await mcp_client.call_tool(
        "update_preferences", {"preference_type": "household_size", "value": 0}
    )

    assert result.data["error"] == "validation_error"
    assert result.data["parameter"] == "household_size"


async def test_log_meal_happy_path(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool(
        "log_meal",
        {
            "recipe_id": None,
            "recipe_name": "Test Dinner",
            "cuisine": "italian",
            "meal_type": "dinner",
            "date": date.today().isoformat(),
        },
    )

    assert result.data["recipe_name"] == "Test Dinner"
    assert result.data["rating"] is None


async def test_log_meal_out_of_range_rating_returns_validation_error(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool(
        "log_meal",
        {
            "recipe_id": None,
            "recipe_name": "Test",
            "cuisine": None,
            "meal_type": None,
            "date": date.today().isoformat(),
            "rating": 6,
        },
    )

    assert result.data["error"] == "validation_error"
    assert result.data["parameter"] == "rating"


async def test_get_meal_history_happy_path(mcp_client: Client[Any]) -> None:
    await mcp_client.call_tool(
        "log_meal",
        {
            "recipe_id": None,
            "recipe_name": "Test",
            "cuisine": "thai",
            "meal_type": "dinner",
            "date": date.today().isoformat(),
        },
    )

    result = await mcp_client.call_tool("get_meal_history", {})

    assert result.data["count"] == 1
    assert result.data["meals"][0]["recipe_name"] == "Test"


async def test_check_repetition_happy_path(mcp_client: Client[Any]) -> None:
    await insert_recipe(recipe_id="r1", name="Tacos", cuisine="mexican", ingredients=["beef"])

    result = await mcp_client.call_tool("check_repetition", {"recipe_id": "r1"})

    assert result.data["recommendation"] == "acceptable"
    assert result.data["last_cooked"] is None


async def test_check_repetition_unknown_recipe_returns_structured_not_found(
    mcp_client: Client[Any],
) -> None:
    result = await mcp_client.call_tool("check_repetition", {"recipe_id": "does-not-exist"})

    assert result.data["error"] == "not_found"
    assert "does-not-exist" in result.data["message"]


async def test_get_context_signals_happy_path(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool(
        "get_context_signals", {"current_time": "2026-01-05T18:30:00", "day_of_week": 0}
    )

    assert result.data["meal_type"] == "dinner"
    assert len(result.data["context_notes"]) >= 1
