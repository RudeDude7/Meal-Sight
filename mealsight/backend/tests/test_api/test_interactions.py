"""Tests for GET /api/interactions — a thin proxy onto user_intelligence's
own get_interaction_history tool. Same FakeManager/running_client
convention as tests/test_api/test_app.py."""

from __future__ import annotations

import json

from mealsight.agent.mcp_client import ToolCallResult
from tests.test_api.test_app import FakeManager, running_client

INTERACTIONS_DATA = {
    "interactions": [
        {
            "id": 2,
            "created_at": "2026-08-27T10:00:00",
            "trace_id": "t2",
            "modalities": ["text"],
            "text_input": "something quick",
            "voice_transcript": None,
            "ingredients_summary": None,
            "merged_constraints": None,
            "recommended_recipe_id": None,
            "recommended_recipe_name": None,
            "any_cookable": False,
            "top_match_score": 0.4,
            "final_response": "Nothing cookable this run.",
        },
        {
            "id": 1,
            "created_at": "2026-08-27T09:00:00",
            "trace_id": "t1",
            "modalities": ["vision"],
            "text_input": None,
            "voice_transcript": None,
            "ingredients_summary": "Found 3 item(s): egg, milk, butter",
            "merged_constraints": {"dietary_restrictions": []},
            "recommended_recipe_id": "r1",
            "recommended_recipe_name": "Omelette",
            "any_cookable": True,
            "top_match_score": 0.95,
            "final_response": "Make an omelette.",
        },
    ],
    "count": 2,
}


async def test_get_interactions_proxies_to_the_mcp_tool() -> None:
    manager = FakeManager(
        {
            ("user_intelligence", "get_interaction_history"): ToolCallResult(
                success=True, data=INTERACTIONS_DATA
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/interactions")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [row["trace_id"] for row in body["interactions"]] == ["t2", "t1"]


async def test_get_interactions_passes_query_params_through() -> None:
    manager = FakeManager(
        {
            ("user_intelligence", "get_interaction_history"): ToolCallResult(
                success=True, data=INTERACTIONS_DATA
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        await client.get("/api/interactions", params={"days_back": 7, "limit": 5})

    call = next(c for c in manager.calls if c[:2] == ("user_intelligence", "get_interaction_history"))
    assert call[2] == {"days_back": 7, "limit": 5}


async def test_no_interaction_row_ever_contains_binary_data() -> None:
    manager = FakeManager(
        {
            ("user_intelligence", "get_interaction_history"): ToolCallResult(
                success=True, data=INTERACTIONS_DATA
            )
        }
    )
    async with running_client(manager) as (client, _manager):
        response = await client.get("/api/interactions")

    # A JSON response can't carry raw bytes at all — this asserts the
    # stronger, more direct thing: nothing in the payload even LOOKS
    # like a base64-style media dump (long unbroken alphanumeric blob),
    # which a byte-smuggling bug would produce even through JSON.
    raw = json.dumps(response.json())
    for row in response.json()["interactions"]:
        for value in row.values():
            if isinstance(value, str):
                assert len(value) < 500, f"suspiciously large string field: {value[:50]}..."
    assert "\\x" not in raw
