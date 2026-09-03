"""Tests for the pantry-manager MCP tools' actual behavior, called
through the real FastMCP in-memory client."""

from __future__ import annotations

from typing import Any

from fastmcp import Client

from tests.test_mcp_servers.test_pantry_manager.conftest import insert_pantry_item, insert_shelf_life

_ONION_ITEM = {"name": "onion", "quantity": 2.0, "unit": "count", "category": "vegetable"}
_GARLIC_ITEM = {"name": "garlic", "quantity": 1.0, "unit": "count", "category": "vegetable"}


async def test_update_pantry_happy_path_adds_new_items(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool(
        "update_pantry",
        {
            "items": [
                {"name": "onion", "quantity": 2.0, "unit": "count", "category": "vegetable"},
                {"name": "milk", "quantity": 1.0, "unit": "liter", "category": "dairy"},
            ]
        },
    )

    assert result.data["added_count"] == 2
    assert result.data["updated_count"] == 0
    actions = {d["name"]: d["action"] for d in result.data["details"]}
    assert actions == {"onion": "added", "milk": "added"}


async def test_update_pantry_accumulates_rather_than_replacing(mcp_client: Client[Any]) -> None:
    await mcp_client.call_tool("update_pantry", {"items": [_ONION_ITEM]})

    result = await mcp_client.call_tool(
        "update_pantry", {"items": [{**_ONION_ITEM, "quantity": 3.0}]}
    )

    assert result.data["added_count"] == 0
    assert result.data["updated_count"] == 1
    assert result.data["details"][0]["quantity_after"] == 5.0

    pantry = await mcp_client.call_tool("get_pantry", {})
    onion_rows = [item for item in pantry.data["items"] if item["name"] == "onion"]
    assert len(onion_rows) == 1
    assert onion_rows[0]["quantity"] == 5.0


async def test_update_pantry_never_deletes_items_absent_from_the_batch(mcp_client: Client[Any]) -> None:
    await mcp_client.call_tool("update_pantry", {"items": [_ONION_ITEM]})
    await mcp_client.call_tool("update_pantry", {"items": [_GARLIC_ITEM]})

    pantry = await mcp_client.call_tool("get_pantry", {})
    names = {item["name"] for item in pantry.data["items"]}
    assert names == {"onion", "garlic"}


async def test_get_pantry_happy_path_with_filters(mcp_client: Client[Any]) -> None:
    await insert_pantry_item(name="onion", category="vegetable")
    await insert_pantry_item(name="milk", category="dairy")

    result = await mcp_client.call_tool("get_pantry", {"category": "dairy"})

    assert result.data["count"] == 1
    assert result.data["items"][0]["name"] == "milk"


async def test_get_pantry_invalid_freshness_filter_returns_validation_error(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool("get_pantry", {"freshness_filter": "bogus"})

    assert result.data["error"] == "validation_error"
    assert result.data["parameter"] == "freshness_filter"
    assert set(result.data["accepted_values"]) == {"expiring_soon", "fresh", "all"}


async def test_remove_items_happy_path(mcp_client: Client[Any]) -> None:
    await insert_pantry_item(name="onion", quantity=5.0)

    result = await mcp_client.call_tool(
        "remove_items",
        {"items": [{"name": "onion", "quantity_used": 2.0}], "recipe_name": "Onion Soup"},
    )

    detail = result.data["details"][0]
    assert detail["found"] is True
    assert detail["quantity_removed"] == 2.0
    assert detail["quantity_remaining"] == 3.0


async def test_remove_items_unknown_item_returns_structured_not_found_detail(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool(
        "remove_items", {"items": [{"name": "unobtainium", "quantity_used": 1.0}]}
    )

    detail = result.data["details"][0]
    assert detail["found"] is False
    assert detail["discrepancy"] == 1.0


async def test_flag_expiring_happy_path(mcp_client: Client[Any]) -> None:
    await insert_pantry_item(name="spinach", category="vegetable", estimated_shelf_days=3, added_days_ago=5)

    result = await mcp_client.call_tool("flag_expiring", {})

    assert result.data["count"] == 1
    assert result.data["items"][0]["name"] == "spinach"
    assert result.data["items"][0]["days_remaining"] < 0


async def test_create_grocery_list_happy_path(mcp_client: Client[Any]) -> None:
    await insert_shelf_life("soy sauce", "condiment")

    result = await mcp_client.call_tool(
        "create_grocery_list",
        {
            "missing_by_recipe": [
                {
                    "recipe_id": "1",
                    "recipe_name": "Stir Fry",
                    "missing_ingredients": [
                        {"name": "soy sauce", "quantity": 2.0, "unit": "tbsp", "importance": "critical"}
                    ],
                }
            ]
        },
    )

    assert result.data["status"] == "active"
    all_items = [item for section in result.data["sections"] for item in section["items"]]
    assert [item["name"] for item in all_items] == ["soy sauce"]
    assert all_items[0]["needed_for"] == ["Stir Fry"]


async def test_get_grocery_list_happy_path(mcp_client: Client[Any]) -> None:
    created = await mcp_client.call_tool(
        "create_grocery_list",
        {
            "missing_by_recipe": [
                {
                    "recipe_id": "1",
                    "recipe_name": "Stir Fry",
                    "missing_ingredients": [
                        {"name": "garlic", "quantity": None, "unit": None, "importance": "optional"}
                    ],
                }
            ]
        },
    )

    result = await mcp_client.call_tool("get_grocery_list", {"list_id": created.data["id"]})

    assert result.data["id"] == created.data["id"]


async def test_get_grocery_list_no_active_list_returns_structured_not_found(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool("get_grocery_list", {})

    assert result.data["error"] == "not_found"


async def test_log_waste_happy_path_deducts_the_pantry(mcp_client: Client[Any]) -> None:
    await insert_pantry_item(name="spinach", quantity=5.0)

    result = await mcp_client.call_tool(
        "log_waste", {"item_name": "spinach", "quantity_wasted": 2.0, "unit": "count", "reason": "spoiled"}
    )

    assert result.data["reason"] == "spoiled"
    assert result.data["removal"]["quantity_removed"] == 2.0
    assert result.data["insight"] is None


async def test_log_waste_invalid_reason_returns_validation_error(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool(
        "log_waste", {"item_name": "spinach", "quantity_wasted": 1.0, "unit": None, "reason": "bogus"}
    )

    assert result.data["error"] == "validation_error"
    assert result.data["parameter"] == "reason"
    assert set(result.data["accepted_values"]) == {"expired", "spoiled", "didn_t_like", "too_much"}


async def test_log_waste_insight_appears_at_the_threshold_through_the_real_mcp_tool(
    mcp_client: Client[Any],
) -> None:
    for _ in range(2):
        result = await mcp_client.call_tool(
            "log_waste",
            {"item_name": "spinach", "quantity_wasted": 1.0, "unit": "bag", "reason": "expired"},
        )
        assert result.data["insight"] is None

    result = await mcp_client.call_tool(
        "log_waste", {"item_name": "spinach", "quantity_wasted": 1.0, "unit": "bag", "reason": "expired"}
    )
    assert result.data["insight"] is not None
    assert "spinach" in result.data["insight"]


async def test_get_waste_stats_happy_path(mcp_client: Client[Any]) -> None:
    await mcp_client.call_tool(
        "log_waste", {"item_name": "spinach", "quantity_wasted": 1.0, "unit": "bag", "reason": "expired"}
    )

    result = await mcp_client.call_tool("get_waste_stats", {"time_range": "all_time"})

    assert result.data["time_range"] == "all_time"
    assert result.data["total_items_wasted"] == 1
    assert result.data["most_wasted"][0]["item_name"] == "spinach"
    assert result.data["trend"]["change_pct"] is None  # all_time has no previous period


async def test_get_waste_stats_invalid_time_range_returns_validation_error(mcp_client: Client[Any]) -> None:
    result = await mcp_client.call_tool("get_waste_stats", {"time_range": "bogus"})

    assert result.data["error"] == "validation_error"
    assert result.data["parameter"] == "time_range"
    assert set(result.data["accepted_values"]) == {"this_week", "this_month", "all_time"}
