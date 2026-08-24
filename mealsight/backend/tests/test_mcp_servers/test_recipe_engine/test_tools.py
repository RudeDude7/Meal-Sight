"""Tests for the recipe-engine MCP tools' actual behavior, called
through the real FastMCP in-memory client."""

from __future__ import annotations

from typing import Any

from fastmcp import Client

from tests.test_mcp_servers.test_recipe_engine.conftest import (
    insert_nutrition,
    insert_recipe,
    insert_substitution,
)

_ONION = {"name": "onion", "quantity": 1.0, "unit": None, "importance": "important", "raw_measure": "1"}


async def test_search_recipes_happy_path_returns_summaries_with_total_matched(
    mcp_client: Client[Any],
) -> None:
    await insert_recipe(
        recipe_id="1",
        name="Vegan Stew",
        ingredients=[_ONION],
        cook_time_minutes=20,
        dietary_tags=["vegan"],
        steps=["Step one.", "Step two."],
    )
    await insert_recipe(
        recipe_id="2",
        name="Beef Stew",
        ingredients=[_ONION],
        cook_time_minutes=20,
        dietary_tags=[],
    )

    result = await mcp_client.call_tool("search_recipes", {"dietary_filters": ["vegan"], "max_cook_time": 30})
    data = result.data

    assert data["total_matched"] == 1
    assert [r["id"] for r in data["results"]] == ["1"]
    # Compact summary only — no steps, no full ingredient records.
    assert "steps" not in data["results"][0]
    assert "ingredients" not in data["results"][0]


async def test_search_recipes_dietary_filter_excludes_not_deprioritizes(mcp_client: Client[Any]) -> None:
    await insert_recipe(recipe_id="1", name="Vegan", ingredients=[_ONION], dietary_tags=["vegan"])
    await insert_recipe(recipe_id="2", name="Beef", ingredients=[_ONION], dietary_tags=[])

    result = await mcp_client.call_tool("search_recipes", {"dietary_filters": ["vegan"]})

    ids = {r["id"] for r in result.data["results"]}
    assert ids == {"1"}


async def test_get_recipe_happy_path(mcp_client: Client[Any]) -> None:
    await insert_recipe(
        recipe_id="1",
        name="Onion Soup",
        ingredients=[_ONION],
        steps=["Chop.", "Simmer."],
        cook_time_minutes=30,
    )

    result = await mcp_client.call_tool("get_recipe", {"recipe_id": "1"})

    assert result.data["name"] == "Onion Soup"
    assert result.data["steps"] == ["Chop.", "Simmer."]


async def test_get_recipe_unknown_id_returns_structured_not_found_not_an_exception(
    mcp_client: Client[Any],
) -> None:
    result = await mcp_client.call_tool("get_recipe", {"recipe_id": "does-not-exist"})

    assert result.is_error is False
    assert result.data["error"] == "not_found"
    assert "does-not-exist" in result.data["message"]


async def test_match_ingredients_happy_path(mcp_client: Client[Any]) -> None:
    await insert_recipe(
        recipe_id="1",
        name="Onion Soup",
        ingredients=[
            {"name": "onion", "quantity": 1.0, "unit": None, "importance": "critical", "raw_measure": "1"}
        ],
    )

    result = await mcp_client.call_tool(
        "match_ingredients", {"recipe_id": "1", "available_ingredients": ["onion"]}
    )

    assert result.data["can_cook"] is True
    assert result.data["match_score"] == 1.0


async def test_match_ingredients_unknown_recipe_id_returns_structured_not_found(
    mcp_client: Client[Any],
) -> None:
    result = await mcp_client.call_tool(
        "match_ingredients", {"recipe_id": "nope", "available_ingredients": ["onion"]}
    )

    assert result.data["error"] == "not_found"
    assert "nope" in result.data["message"]


async def test_scale_recipe_happy_path(mcp_client: Client[Any]) -> None:
    await insert_recipe(
        recipe_id="1",
        name="Test",
        servings_base=4,
        ingredients=[
            {
                "name": "flour",
                "quantity": 1.0,
                "unit": "cup",
                "importance": "important",
                "raw_measure": "1 cup",
            }
        ],
    )

    result = await mcp_client.call_tool("scale_recipe", {"recipe_id": "1", "target_servings": 2})

    assert result.data["ingredients"][0]["quantity_display"] == "1/2"


async def test_scale_recipe_zero_target_servings_returns_validation_error_naming_parameter(
    mcp_client: Client[Any],
) -> None:
    await insert_recipe(recipe_id="1", name="Test", ingredients=[_ONION])

    result = await mcp_client.call_tool("scale_recipe", {"recipe_id": "1", "target_servings": 0})

    assert result.data["error"] == "validation_error"
    assert result.data["parameter"] == "target_servings"


async def test_calculate_nutrition_happy_path(mcp_client: Client[Any]) -> None:
    await insert_nutrition("chicken", calories=165, protein=31, carbs=0, fat=3.6)
    await insert_recipe(
        recipe_id="1",
        name="Test",
        servings_base=1,
        ingredients=[
            {
                "name": "chicken",
                "quantity": 100.0,
                "unit": "g",
                "importance": "critical",
                "raw_measure": "100g",
            }
        ],
    )

    result = await mcp_client.call_tool("calculate_nutrition", {"recipe_id": "1", "servings": 1})

    assert result.data["coverage_pct"] == 100.0
    assert result.data["ingredients_covered"] == 1


async def test_find_substitutions_happy_path(mcp_client: Client[Any]) -> None:
    await insert_substitution("butter", "olive oil", flavor_impact="noticeable")
    await insert_substitution("butter", "vegan margarine", flavor_impact="minimal")

    result = await mcp_client.call_tool(
        "find_substitutions", {"ingredient_name": "butter", "reason": "unavailable"}
    )

    assert result.data["suggestions"][0]["substitute"] == "vegan margarine"


async def test_find_substitutions_invalid_reason_returns_validation_error_naming_accepted_values(
    mcp_client: Client[Any],
) -> None:
    result = await mcp_client.call_tool(
        "find_substitutions", {"ingredient_name": "butter", "reason": "bogus"}
    )

    assert result.data["error"] == "validation_error"
    assert result.data["parameter"] == "reason"
    assert set(result.data["accepted_values"]) == {"unavailable", "allergic", "dietary", "dislike"}
