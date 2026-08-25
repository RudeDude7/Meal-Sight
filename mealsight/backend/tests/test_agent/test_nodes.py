"""Tests for mealsight.agent.nodes' real implementations (1-5):
validate_input, perceive, merge, update_pantry, get_context. No real
MCP servers or providers — a FakeMCP stands in for MCPClientManager,
and mealsight.perception's own analyze_* functions are monkeypatched
where a test needs to control exactly what they return.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from typing import Any, cast

import pytest
from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.mcp_client import MCPClientManager, ToolCallResult
from mealsight.agent.nodes.get_context import get_context
from mealsight.agent.nodes.merge import merge
from mealsight.agent.nodes.perceive import perceive
from mealsight.agent.nodes.update_pantry import update_pantry
from mealsight.agent.nodes.validate_input import validate_input
from mealsight.perception.models import (
    AudioPerception,
    IdentifiedItem,
    TextPerception,
    VisionPerception,
)

# Resolved via importlib.import_module, NOT `import mealsight.agent.
# nodes.perceive as perceive_module`: mealsight.agent.nodes' own
# __init__.py does `from mealsight.agent.nodes.perceive import
# perceive`, which rebinds the `perceive` ATTRIBUTE on the nodes
# package to the FUNCTION — and `import a.b.c as x` resolves through
# that same (now-shadowed) attribute chain, not through sys.modules
# directly, so it silently returns the function instead of the module.
# importlib.import_module looks the real module up in sys.modules and
# isn't fooled by the shadowing.
perceive_module = importlib.import_module("mealsight.agent.nodes.perceive")
update_pantry_module = importlib.import_module("mealsight.agent.nodes.update_pantry")


class FakeMCP:
    """Stands in for MCPClientManager: call_tool returns a pre-baked
    ToolCallResult keyed by (server, tool_name), or a default failure
    if nothing was configured for that key. Records every call it
    receives."""

    def __init__(self, responses: dict[tuple[str, str], ToolCallResult] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_tool(
        self, server: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        self.calls.append((server, tool_name, arguments or {}))
        return self._responses.get((server, tool_name), ToolCallResult(success=False, error="unconfigured"))


def _runtime(mcp: FakeMCP) -> Runtime[AgentContext]:
    return Runtime(context=AgentContext(mcp=cast(MCPClientManager, mcp)))


def _profile_response() -> ToolCallResult:
    return ToolCallResult(
        success=True,
        data={
            "dietary_restrictions": [],
            "disliked_ingredients": [],
            "preferred_cook_time_minutes": 30,
            "household_size": 2,
            "protein_preference": None,
            "cooking_skill": "intermediate",
            "budget_sensitivity": "moderate",
            "cuisine_preferences": {},
        },
    )


def _vision_item(name: str = "onion") -> IdentifiedItem:
    return IdentifiedItem(
        name=name, quantity=1.0, unit="count", category="vegetable", freshness="fresh", confidence="high"
    )


def _vision(items: list[IdentifiedItem] | None = None) -> VisionPerception:
    return VisionPerception(
        identified_items=items or [], total_items_found=len(items or []), photo_quality="clear", notes=None
    )


def _audio(**kwargs: object) -> AudioPerception:
    base: dict[str, object] = {
        "raw_transcript": "test",
        "servings": None,
        "max_cook_time_minutes": None,
        "dietary_restrictions": [],
        "cuisine_preference": None,
        "avoid_ingredients": [],
        "avoid_dishes": [],
        "mood_or_preference": None,
        "protein_preference": None,
        "occasion": None,
        "additional_context": None,
    }
    base.update(kwargs)
    return AudioPerception(**base)  # type: ignore[arg-type]


def _text(**kwargs: object) -> TextPerception:
    base: dict[str, object] = {
        "servings": None,
        "max_cook_time_minutes": None,
        "dietary_restrictions": [],
        "cuisine_preference": None,
        "avoid_ingredients": [],
        "avoid_dishes": [],
        "mood_or_preference": None,
        "protein_preference": None,
        "occasion": None,
        "additional_context": None,
    }
    base.update(kwargs)
    return TextPerception(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------
# validate_input
# --------------------------------------------------------------------


async def test_validate_input_rejects_zero_modalities_and_marks_terminal() -> None:
    result = await validate_input({"stream_messages": []})

    assert result["terminal"] is True
    assert "terminal_reason" in result
    assert len(result["stream_messages"]) == 1


async def test_validate_input_accepts_valid_text() -> None:
    result = await validate_input({"text_input": "2 servings please", "stream_messages": []})

    assert "terminal" not in result
    assert len(result["stream_messages"]) == 1


async def test_validate_input_every_node_appends_a_stream_message() -> None:
    result = await validate_input({"stream_messages": []})
    assert len(result["stream_messages"]) >= 1


# --------------------------------------------------------------------
# perceive
# --------------------------------------------------------------------


async def test_perceive_continues_when_one_modality_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_vision(image_bytes: bytes, **kwargs: object) -> VisionPerception:
        raise RuntimeError("simulated unexpected vision failure")

    async def working_text(text: str, **kwargs: object) -> TextPerception:
        return _text(servings=2)

    monkeypatch.setattr(perceive_module, "analyze_fridge_photo", failing_vision)
    monkeypatch.setattr(perceive_module, "analyze_text_input", working_text)

    result = await perceive(
        {"image_bytes": b"fake", "text_input": "2 servings", "stream_messages": []}
    )

    assert "vision_result" not in result
    assert result["text_result"].servings == 2
    assert len(result["stream_messages"]) == 2  # one per attempted modality


async def test_perceive_skips_when_terminal() -> None:
    result = await perceive({"terminal": True, "stream_messages": []})
    assert "vision_result" not in result
    assert len(result["stream_messages"]) == 1


async def test_perceive_runs_groq_and_mistral_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline: list[tuple[str, float]] = []

    async def slow_vision(image_bytes: bytes, **kwargs: object) -> VisionPerception:
        timeline.append(("vision_start", time.monotonic()))
        await asyncio.sleep(0.1)
        timeline.append(("vision_end", time.monotonic()))
        return _vision()

    async def slow_audio(audio_bytes: bytes, **kwargs: object) -> AudioPerception:
        timeline.append(("audio_start", time.monotonic()))
        await asyncio.sleep(0.1)
        timeline.append(("audio_end", time.monotonic()))
        return _audio()

    monkeypatch.setattr(perceive_module, "analyze_fridge_photo", slow_vision)
    monkeypatch.setattr(perceive_module, "analyze_voice_memo", slow_audio)

    started = time.monotonic()
    await perceive({"image_bytes": b"fake", "audio_bytes": b"fake", "stream_messages": []})
    elapsed = time.monotonic() - started

    # Sequential would take >= 0.2s; concurrent should take ~0.1s.
    assert elapsed < 0.18

    events = dict(timeline)
    assert events["audio_start"] < events["vision_end"]


async def test_perceive_runs_vision_and_text_sequentially_not_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[tuple[str, float]] = []

    async def slow_vision(image_bytes: bytes, **kwargs: object) -> VisionPerception:
        timeline.append(("vision_start", time.monotonic()))
        await asyncio.sleep(0.05)
        timeline.append(("vision_end", time.monotonic()))
        return _vision()

    async def slow_text(text: str, **kwargs: object) -> TextPerception:
        timeline.append(("text_start", time.monotonic()))
        return _text()

    monkeypatch.setattr(perceive_module, "analyze_fridge_photo", slow_vision)
    monkeypatch.setattr(perceive_module, "analyze_text_input", slow_text)

    await perceive({"image_bytes": b"fake", "text_input": "hello", "stream_messages": []})

    events = dict(timeline)
    assert events["text_start"] >= events["vision_end"]


# --------------------------------------------------------------------
# merge
# --------------------------------------------------------------------


async def test_merge_passes_the_profile_through_to_merge_perceptions() -> None:
    mcp = FakeMCP({("user_intelligence", "get_user_profile"): _profile_response()})

    result = await merge(
        {"audio_result": _audio(servings=None), "stream_messages": []}, _runtime(mcp)
    )

    assert ("user_intelligence", "get_user_profile", {}) in mcp.calls
    # Profile's household_size=2 should fill the unspecified servings.
    assert result["unified_request"].servings == 2
    assert result["user_profile"]["household_size"] == 2


async def test_merge_skips_when_terminal() -> None:
    mcp = FakeMCP()
    result = await merge({"terminal": True, "stream_messages": []}, _runtime(mcp))
    assert mcp.calls == []
    assert "unified_request" not in result


async def test_merge_handles_nothing_to_merge_without_raising() -> None:
    mcp = FakeMCP({("user_intelligence", "get_user_profile"): _profile_response()})
    result = await merge({"stream_messages": []}, _runtime(mcp))
    assert "unified_request" not in result
    assert len(result["stream_messages"]) == 1


# --------------------------------------------------------------------
# update_pantry
# --------------------------------------------------------------------


async def test_update_pantry_skips_update_but_still_flags_expiring_when_vision_empty() -> None:
    mcp = FakeMCP(
        {
            ("pantry_manager", "flag_expiring"): ToolCallResult(
                success=True, data={"items": [{"name": "spinach"}], "count": 1}
            ),
        }
    )

    result = await update_pantry({"stream_messages": []}, _runtime(mcp))

    called_tools = [(server, tool) for server, tool, _ in mcp.calls]
    assert ("pantry_manager", "update_pantry") not in called_tools
    assert ("pantry_manager", "flag_expiring") in called_tools
    assert result["expiring_items"] == [{"name": "spinach"}]


async def test_update_pantry_calls_update_when_vision_has_items() -> None:
    mcp = FakeMCP(
        {
            ("pantry_manager", "update_pantry"): ToolCallResult(
                success=True, data={"added_count": 1, "updated_count": 0, "flagged_items": []}
            ),
            ("pantry_manager", "flag_expiring"): ToolCallResult(success=True, data={"items": [], "count": 0}),
        }
    )

    result = await update_pantry(
        {"vision_result": _vision([_vision_item()]), "stream_messages": []}, _runtime(mcp)
    )

    called_tools = [(server, tool) for server, tool, _ in mcp.calls]
    assert ("pantry_manager", "update_pantry") in called_tools
    assert result["expiring_items"] == []


async def test_update_pantry_skips_when_terminal() -> None:
    mcp = FakeMCP()
    result = await update_pantry({"terminal": True, "stream_messages": []}, _runtime(mcp))
    assert mcp.calls == []
    assert len(result["stream_messages"]) == 1


async def test_update_pantry_records_unexpected_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_to_pantry_item_inputs(perception: object) -> object:
        # to_pantry_item_inputs is a plain sync function (phase 5.1) —
        # the fake has to be sync too, or the RuntimeError never
        # actually fires where the real code calls it.
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(update_pantry_module, "to_pantry_item_inputs", broken_to_pantry_item_inputs)
    mcp = FakeMCP({("pantry_manager", "flag_expiring"): ToolCallResult(success=True, data={"items": []})})

    result = await update_pantry(
        {"vision_result": _vision([_vision_item()]), "stream_messages": []}, _runtime(mcp)
    )

    assert any("unexpectedly" in m for m in result["stream_messages"])


# --------------------------------------------------------------------
# get_context
# --------------------------------------------------------------------


async def test_get_context_does_not_refetch_the_profile() -> None:
    mcp = FakeMCP(
        {
            ("user_intelligence", "get_context_signals"): ToolCallResult(
                success=True, data={"meal_type": "dinner", "complexity_suggestion": "keep it simple"}
            ),
            ("user_intelligence", "get_meal_history"): ToolCallResult(
                success=True, data={"meals": [], "count": 0}
            ),
        }
    )

    result = await get_context(
        {"user_profile": {"household_size": 2}, "stream_messages": []}, _runtime(mcp)
    )

    called_tools = {(server, tool) for server, tool, _ in mcp.calls}
    assert ("user_intelligence", "get_user_profile") not in called_tools
    assert called_tools == {
        ("user_intelligence", "get_context_signals"),
        ("user_intelligence", "get_meal_history"),
    }
    assert result["context_signals"]["meal_type"] == "dinner"
    assert result["meal_history"] == []


async def test_get_context_skips_when_terminal() -> None:
    mcp = FakeMCP()
    result = await get_context({"terminal": True, "stream_messages": []}, _runtime(mcp))
    assert mcp.calls == []
    assert len(result["stream_messages"]) == 1
