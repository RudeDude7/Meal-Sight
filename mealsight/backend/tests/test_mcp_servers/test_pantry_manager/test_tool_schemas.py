"""Confirms the eight pantry-manager tools are all registered, described,
and schema'd the way an MCP client (and, later, an agent selecting among
them) actually needs — using the real FastMCP in-memory client, so this
exercises the real MCP protocol, not just server.py's Python functions
directly."""

from __future__ import annotations

from typing import Any

from fastmcp import Client

EXPECTED_TOOLS: dict[str, set[str]] = {
    "update_pantry": {"items"},
    "get_pantry": {"category", "freshness_filter", "search"},
    "remove_items": {"items", "recipe_name"},
    "flag_expiring": {"days_threshold"},
    "create_grocery_list": {"missing_by_recipe"},
    "get_grocery_list": {"list_id"},
    "log_waste": {"item_name", "quantity_wasted", "unit", "reason"},
    "get_waste_stats": {"time_range"},
}


async def test_all_eight_tools_are_listed_with_non_empty_descriptions(mcp_client: Client[Any]) -> None:
    tools = await mcp_client.list_tools()
    names = {t.name for t in tools}

    assert names == set(EXPECTED_TOOLS)
    for tool in tools:
        assert tool.description is not None
        assert len(tool.description.strip()) > 50, f"{tool.name}'s description is suspiciously short"


async def test_each_tool_has_the_correct_parameter_schema(mcp_client: Client[Any]) -> None:
    tools = {t.name: t for t in await mcp_client.list_tools()}

    for tool_name, expected_params in EXPECTED_TOOLS.items():
        schema = tools[tool_name].inputSchema
        actual_params = set(schema.get("properties", {}).keys())
        assert actual_params == expected_params, f"{tool_name} schema mismatch"


async def test_create_grocery_list_schema_shows_nested_recipe_shape(mcp_client: Client[Any]) -> None:
    tools = {t.name: t for t in await mcp_client.list_tools()}
    schema = tools["create_grocery_list"].inputSchema

    items_schema = schema["properties"]["missing_by_recipe"]
    # FastMCP auto-derives the full nested pydantic schema from the
    # RecipeMissingIngredients / MissingIngredientInput type hints —
    # this confirms recipe_id/recipe_name/missing_ingredients (and its
    # own nested name/quantity/unit/importance) actually show up, not
    # just an opaque "object" or "array".
    assert items_schema["type"] == "array"
    recipe_props = items_schema["items"]["properties"]
    assert set(recipe_props) == {"recipe_id", "recipe_name", "missing_ingredients"}

    ingredient_props = recipe_props["missing_ingredients"]["items"]["properties"]
    assert set(ingredient_props) == {"name", "quantity", "unit", "importance"}


async def test_update_pantry_description_states_it_adds_and_never_deletes(mcp_client: Client[Any]) -> None:
    tools = {t.name: t for t in await mcp_client.list_tools()}
    description = (tools["update_pantry"].description or "").lower()

    assert "add" in description
    assert "never" in description and "delete" in description


async def test_remove_items_description_states_it_is_called_after_cooking_is_confirmed(
    mcp_client: Client[Any],
) -> None:
    tools = {t.name: t for t in await mcp_client.list_tools()}
    description = (tools["remove_items"].description or "").lower()

    assert "after" in description
    assert "confirmed" in description or "actually" in description


async def test_log_waste_description_states_it_deducts_from_the_pantry(mcp_client: Client[Any]) -> None:
    tools = {t.name: t for t in await mcp_client.list_tools()}
    description = (tools["log_waste"].description or "").lower()

    assert "deduct" in description
    assert "remove_items" in description
