"""Confirms the nine user-intelligence tools are all registered,
described, and schema'd the way an MCP client (and, later, an agent
selecting among them) actually needs — using the real FastMCP in-memory
client, so this exercises the real MCP protocol, not just server.py's
Python functions called directly."""

from __future__ import annotations

from typing import Any

from fastmcp import Client

EXPECTED_TOOLS: dict[str, set[str]] = {
    "get_user_profile": set(),
    "update_preferences": {"preference_type", "value"},
    "log_meal": {
        "recipe_id",
        "recipe_name",
        "cuisine",
        "meal_type",
        "date",
        "rating",
        "servings_made",
        "ingredients_used",
        "notes",
    },
    "rate_meal": {"meal_id", "rating"},
    "get_meal_history": {"days_back", "cuisine_filter", "rating_filter"},
    "check_repetition": {"recipe_id", "check_window_days"},
    "get_context_signals": {"current_time", "day_of_week"},
    "record_interaction": {
        "trace_id",
        "modalities",
        "text_input",
        "voice_transcript",
        "ingredients_summary",
        "merged_constraints",
        "recommended_recipe_id",
        "recommended_recipe_name",
        "any_cookable",
        "top_match_score",
        "final_response",
    },
    "get_interaction_history": {"days_back", "limit"},
}


async def test_all_nine_tools_are_listed_with_non_empty_descriptions(mcp_client: Client[Any]) -> None:
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


async def test_log_meal_description_states_it_is_called_only_after_cooking_is_confirmed(
    mcp_client: Client[Any],
) -> None:
    tools = {t.name: t for t in await mcp_client.list_tools()}
    description = (tools["log_meal"].description or "").lower()

    assert "after" in description
    assert "confirmed" in description
    assert "never" in description


async def test_check_repetition_description_states_it_is_not_a_hard_veto(mcp_client: Client[Any]) -> None:
    tools = {t.name: t for t in await mcp_client.list_tools()}
    description = (tools["check_repetition"].description or "").lower()

    assert "signal to weigh" in description or "not a hard veto" in description
    assert "veto" in description
