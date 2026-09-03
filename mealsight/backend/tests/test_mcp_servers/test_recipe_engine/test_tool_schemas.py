"""Confirms the six recipe-engine tools are all registered, described,
and schema'd the way an MCP client (and, later, an agent selecting among
them) actually needs — using the real FastMCP in-memory client, so this
exercises the real MCP protocol, not just server.py's Python functions
directly."""

from __future__ import annotations

from typing import Any

from fastmcp import Client

EXPECTED_TOOLS: dict[str, set[str]] = {
    "search_recipes": {
        "dietary_filters",
        "max_cook_time",
        "cuisine",
        "meal_type",
        "max_results",
        "pantry_ingredients",
    },
    "get_recipe": {"recipe_id"},
    "match_ingredients": {"recipe_id", "available_ingredients", "dietary_restrictions"},
    "scale_recipe": {"recipe_id", "target_servings"},
    "calculate_nutrition": {"recipe_id", "servings"},
    "find_substitutions": {"ingredient_name", "reason"},
}


async def test_all_six_tools_are_listed_with_non_empty_descriptions(mcp_client: Client[Any]) -> None:
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


async def test_search_recipes_description_states_it_does_not_match_ingredients(
    mcp_client: Client[Any],
) -> None:
    tools = {t.name: t for t in await mcp_client.list_tools()}
    description = (tools["search_recipes"].description or "").lower()

    assert "not" in description
    assert "match_ingredients" in description
