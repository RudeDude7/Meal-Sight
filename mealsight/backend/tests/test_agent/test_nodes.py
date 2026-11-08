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
from pydantic import BaseModel

from mealsight.agent.context import AgentContext
from mealsight.agent.mcp_client import MCPClientManager, ToolCallResult
from mealsight.agent.nodes.generate_output import generate_output
from mealsight.agent.nodes.get_context import get_context
from mealsight.agent.nodes.match_rank import match_rank
from mealsight.agent.nodes.merge import merge
from mealsight.agent.nodes.perceive import perceive
from mealsight.agent.nodes.present import present
from mealsight.agent.nodes.reason import RecipeDecision, reason
from mealsight.agent.nodes.record_outcome import record_outcome
from mealsight.agent.nodes.search_recipes import search_recipes
from mealsight.agent.nodes.update_pantry import update_pantry
from mealsight.agent.nodes.validate_input import validate_input
from mealsight.agent.state import MealSightState
from mealsight.perception.models import (
    AudioPerception,
    AvailableIngredient,
    IdentifiedItem,
    TextPerception,
    UnifiedMealRequest,
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
reason_module = importlib.import_module("mealsight.agent.nodes.reason")
generate_output_module = importlib.import_module("mealsight.agent.nodes.generate_output")
present_module = importlib.import_module("mealsight.agent.nodes.present")


class FakeMCP:
    """Stands in for MCPClientManager: call_tool returns a pre-baked
    ToolCallResult keyed by (server, tool_name), or a default failure
    if nothing was configured for that key. Records every call it
    receives."""

    def __init__(self, responses: dict[tuple[str, str], ToolCallResult] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._call_log: list[dict[str, Any]] = []

    async def call_tool(
        self, server: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        self.calls.append((server, tool_name, arguments or {}))
        result = self._responses.get((server, tool_name), ToolCallResult(success=False, error="unconfigured"))
        self._call_log.append(
            {
                "server": server,
                "tool": tool_name,
                "duration_ms": 0.0,
                "success": result.success,
                "attempts": 1,
            }
        )
        return result

    def get_call_log(self) -> list[dict[str, Any]]:
        return list(self._call_log)


def _runtime(mcp: FakeMCP) -> Runtime[AgentContext]:
    return Runtime(context=AgentContext(mcp=cast(MCPClientManager, mcp)))


class FakeStream:
    """Stands in for mealsight.api.streaming.SessionStream — records
    every (event_type, fields) a node emits, without any of the real
    buffering/fan-out machinery a WebSocket test needs (see tests/
    test_api/test_ws.py for that layer)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **fields: Any) -> None:
        self.events.append((event_type, fields))


def _runtime_with_stream(mcp: FakeMCP, stream: FakeStream) -> Runtime[AgentContext]:
    return Runtime(context=AgentContext(mcp=cast(MCPClientManager, mcp), stream=stream))


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
            "cuisine_preference_data_points": {},
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


def _unified(**kwargs: object) -> UnifiedMealRequest:
    base: dict[str, object] = {
        "available_ingredients": [],
        "freshness_alerts": [],
        "servings": 2,
        "max_cook_time_minutes": None,
        "dietary_restrictions": [],
        "cuisine_preference": None,
        "avoid_ingredients": [],
        "avoid_dishes": [],
        "mood_or_preference": None,
        "protein_preference": None,
        "occasion": None,
        "modalities_received": ["text"],
        "conflicts_detected": [],
    }
    base.update(kwargs)
    return UnifiedMealRequest(**base)  # type: ignore[arg-type]


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
        {"image_bytes": b"fake", "text_input": "2 servings", "stream_messages": []},
        _runtime(FakeMCP()),
    )

    assert "vision_result" not in result
    assert result["text_result"].servings == 2
    assert len(result["stream_messages"]) == 2  # one per attempted modality


async def test_perceive_skips_when_terminal() -> None:
    result = await perceive({"terminal": True, "stream_messages": []}, _runtime(FakeMCP()))
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
    await perceive(
        {"image_bytes": b"fake", "audio_bytes": b"fake", "stream_messages": []}, _runtime(FakeMCP())
    )
    elapsed = time.monotonic() - started

    # Sequential would take >= 0.2s; concurrent should take ~0.1s.
    assert elapsed < 0.18

    events = dict(timeline)
    assert events["audio_start"] < events["vision_end"]


async def test_perceive_runs_vision_and_text_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reopened this phase (see perceive's own module docstring): the
    # rate limiter keys buckets per model id, not per provider. Vision
    # and text extraction now both run on ministral-8b-2512, so they share
    # one bucket (the test mocks the calls, so the real limit is not in play).
    timeline: list[tuple[str, float]] = []

    async def slow_vision(image_bytes: bytes, **kwargs: object) -> VisionPerception:
        timeline.append(("vision_start", time.monotonic()))
        await asyncio.sleep(0.1)
        timeline.append(("vision_end", time.monotonic()))
        return _vision()

    async def slow_text(text: str, **kwargs: object) -> TextPerception:
        timeline.append(("text_start", time.monotonic()))
        await asyncio.sleep(0.1)
        timeline.append(("text_end", time.monotonic()))
        return _text()

    monkeypatch.setattr(perceive_module, "analyze_fridge_photo", slow_vision)
    monkeypatch.setattr(perceive_module, "analyze_text_input", slow_text)

    started = time.monotonic()
    await perceive(
        {"image_bytes": b"fake", "text_input": "hello", "stream_messages": []}, _runtime(FakeMCP())
    )
    elapsed = time.monotonic() - started

    # Sequential would take >= 0.2s; concurrent should take ~0.1s.
    assert elapsed < 0.18

    events = dict(timeline)
    assert events["text_start"] < events["vision_end"]


async def test_perceive_runs_all_three_modalities_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline: list[tuple[str, float]] = []

    async def slow_vision(image_bytes: bytes, **kwargs: object) -> VisionPerception:
        timeline.append(("vision_start", time.monotonic()))
        await asyncio.sleep(0.1)
        return _vision()

    async def slow_audio(audio_bytes: bytes, **kwargs: object) -> AudioPerception:
        timeline.append(("audio_start", time.monotonic()))
        await asyncio.sleep(0.1)
        return _audio()

    async def slow_text(text: str, **kwargs: object) -> TextPerception:
        timeline.append(("text_start", time.monotonic()))
        await asyncio.sleep(0.1)
        return _text()

    monkeypatch.setattr(perceive_module, "analyze_fridge_photo", slow_vision)
    monkeypatch.setattr(perceive_module, "analyze_voice_memo", slow_audio)
    monkeypatch.setattr(perceive_module, "analyze_text_input", slow_text)

    started = time.monotonic()
    await perceive(
        {
            "image_bytes": b"fake",
            "audio_bytes": b"fake",
            "text_input": "hello",
            "stream_messages": [],
        },
        _runtime(FakeMCP()),
    )
    elapsed = time.monotonic() - started

    # Sequential would take >= 0.3s; concurrent should take ~0.1s.
    assert elapsed < 0.2

    starts = sorted(timeline, key=lambda pair: pair[1])
    # All three should have STARTED within a small window of each
    # other — not one only starting after another has already finished.
    assert starts[-1][1] - starts[0][1] < 0.05


async def test_perceive_emits_a_start_message_per_modality_before_its_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_order: list[str] = []

    async def fake_vision(image_bytes: bytes, **kwargs: object) -> VisionPerception:
        call_order.append("vision_call_started")
        return _vision()

    async def fake_audio(audio_bytes: bytes, **kwargs: object) -> AudioPerception:
        call_order.append("audio_call_started")
        return _audio()

    async def fake_text(text: str, **kwargs: object) -> TextPerception:
        call_order.append("text_call_started")
        return _text()

    monkeypatch.setattr(perceive_module, "analyze_fridge_photo", fake_vision)
    monkeypatch.setattr(perceive_module, "analyze_voice_memo", fake_audio)
    monkeypatch.setattr(perceive_module, "analyze_text_input", fake_text)

    stream = FakeStream()
    await perceive(
        {
            "image_bytes": b"fake",
            "audio_bytes": b"fake",
            "text_input": "hello",
            "stream_messages": [],
        },
        _runtime_with_stream(FakeMCP(), stream),
    )

    # Every modality's own FIRST emitted event is its start message, not
    # its completion message — confirming the start message fires
    # before the provider call, not just that it exists somewhere in
    # the stream.
    first_event_per_modality: dict[str, str] = {}
    for event_type, fields in stream.events:
        if event_type == "ingredient_found":
            first_event_per_modality.setdefault(fields["modality"], fields["message"])

    assert first_event_per_modality["vision"] == perceive_module._START_MESSAGES["vision"]
    assert first_event_per_modality["audio"] == perceive_module._START_MESSAGES["audio"]
    assert first_event_per_modality["text"] == perceive_module._START_MESSAGES["text"]
    assert set(call_order) == {"vision_call_started", "audio_call_started", "text_call_started"}


async def test_perceive_emits_heartbeats_during_a_slow_call_and_stops_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(perceive_module, "HEARTBEAT_INTERVAL_SECONDS", 0.05)

    async def slow_vision(image_bytes: bytes, **kwargs: object) -> VisionPerception:
        await asyncio.sleep(0.22)
        return _vision()

    monkeypatch.setattr(perceive_module, "analyze_fridge_photo", slow_vision)

    stream = FakeStream()
    await perceive(
        {"image_bytes": b"fake", "stream_messages": []},
        _runtime_with_stream(FakeMCP(), stream),
    )

    vision_events = [
        fields["message"] for event_type, fields in stream.events if event_type == "ingredient_found"
    ]
    # start + at least a couple heartbeats + completion, and no more
    # heartbeats appear after the call itself actually finished (the
    # last event is always the real completion message, never a
    # heartbeat).
    assert vision_events[0] == perceive_module._START_MESSAGES["vision"]
    assert len(vision_events) >= 4
    assert vision_events[-1] == "[perceive] Couldn't identify anything in the photo (no items found)."
    heartbeat_texts = set(perceive_module._HEARTBEAT_MESSAGES["vision"])
    middle_events = vision_events[1:-1]
    assert middle_events  # at least one heartbeat actually fired
    assert all(message in heartbeat_texts for message in middle_events)


async def test_perceive_emits_ingredient_found_per_modality(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_vision(image_bytes: bytes, **kwargs: object) -> VisionPerception:
        return _vision([_vision_item()])

    async def fake_audio(audio_bytes: bytes, **kwargs: object) -> AudioPerception:
        return _audio(raw_transcript="two servings please")

    async def fake_text(text: str, **kwargs: object) -> TextPerception:
        return _text(servings=2)

    monkeypatch.setattr(perceive_module, "analyze_fridge_photo", fake_vision)
    monkeypatch.setattr(perceive_module, "analyze_voice_memo", fake_audio)
    monkeypatch.setattr(perceive_module, "analyze_text_input", fake_text)

    stream = FakeStream()
    await perceive(
        {
            "image_bytes": b"fake",
            "audio_bytes": b"fake",
            "text_input": "2 servings",
            "stream_messages": [],
        },
        _runtime_with_stream(FakeMCP(), stream),
    )

    modalities_emitted = {
        event_fields["modality"]
        for event_type, event_fields in stream.events
        if event_type == "ingredient_found"
    }
    assert modalities_emitted == {"vision", "audio", "text"}


# --------------------------------------------------------------------
# merge
# --------------------------------------------------------------------


async def test_merge_passes_the_profile_through_to_merge_perceptions() -> None:
    mcp = FakeMCP({("user_intelligence", "get_user_profile"): _profile_response()})

    result = await merge({"audio_result": _audio(servings=None), "stream_messages": []}, _runtime(mcp))

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


async def test_update_pantry_separates_long_expired_items_into_waste_candidates() -> None:
    mcp = FakeMCP(
        {
            ("pantry_manager", "flag_expiring"): ToolCallResult(
                success=True,
                data={
                    "items": [
                        {"name": "chicken thigh", "days_remaining": -51, "quantity": 5.0, "unit": "lb"},
                        {"name": "egg", "days_remaining": -1, "quantity": 3.0, "unit": "count"},
                        {"name": "ham", "days_remaining": 2, "quantity": 1.0, "unit": "pack"},
                    ],
                    "count": 3,
                },
            ),
        }
    )

    result = await update_pantry({"stream_messages": []}, _runtime(mcp))

    # Only items still inside the grace window are freshness opportunities.
    assert [i["name"] for i in result["expiring_items"]] == ["egg", "ham"]
    assert [i["name"] for i in result["waste_candidates"]] == ["chicken thigh"]
    assert result["waste_candidates"][0]["days_overdue"] == 51
    assert any("treated as waste" in m and "chicken thigh" in m for m in result["stream_messages"])


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


async def test_update_pantry_populates_pantry_items_from_get_pantry() -> None:
    mcp = FakeMCP(
        {
            ("pantry_manager", "flag_expiring"): ToolCallResult(success=True, data={"items": [], "count": 0}),
            ("pantry_manager", "get_pantry"): ToolCallResult(
                success=True,
                data={"items": [{"name": "onion"}, {"name": "green onion"}], "count": 2},
            ),
        }
    )

    result = await update_pantry({"stream_messages": []}, _runtime(mcp))

    called_tools = [(server, tool) for server, tool, _ in mcp.calls]
    assert ("pantry_manager", "get_pantry") in called_tools
    assert result["pantry_items"] == [{"name": "onion"}, {"name": "green onion"}]


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

    result = await get_context({"user_profile": {"household_size": 2}, "stream_messages": []}, _runtime(mcp))

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


# --------------------------------------------------------------------
# search_recipes
# --------------------------------------------------------------------


def _recipe(recipe_id: str = "r1", **kwargs: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "recipe_id": recipe_id,
        "name": f"Recipe {recipe_id}",
        "cuisine": "italian",
        "cook_time_minutes": 20,
        "dietary_tags": [],
    }
    base.update(kwargs)
    return base


class SequencedMCP:
    """Like FakeMCP, but each (server, tool) key holds a QUEUE of
    responses consumed in call order — needed for search_recipes' own
    relaxation retries, where the same tool is called multiple times
    with different arguments and must return a different result each
    time."""

    def __init__(self, sequence: dict[tuple[str, str], list[ToolCallResult]] | None = None) -> None:
        self._sequence = {k: list(v) for k, v in (sequence or {}).items()}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_tool(
        self, server: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        self.calls.append((server, tool_name, arguments or {}))
        queue = self._sequence.get((server, tool_name))
        if queue:
            return queue.pop(0)
        return ToolCallResult(success=False, error="unconfigured")


def _sequenced_runtime(mcp: SequencedMCP) -> Runtime[AgentContext]:
    return Runtime(context=AgentContext(mcp=cast(MCPClientManager, mcp)))


def _fake_runtime(mcp: object) -> Runtime[AgentContext]:
    return Runtime(context=AgentContext(mcp=cast(MCPClientManager, mcp)))


def _fake_runtime_with_stream(mcp: object, stream: FakeStream) -> Runtime[AgentContext]:
    return Runtime(context=AgentContext(mcp=cast(MCPClientManager, mcp), stream=stream))


async def test_search_recipes_succeeds_on_first_try_no_relaxation() -> None:
    mcp = SequencedMCP(
        {
            ("recipe_engine", "search_recipes"): [
                ToolCallResult(success=True, data={"results": [_recipe()], "total_matched": 1})
            ]
        }
    )
    state: MealSightState = {
        "unified_request": _unified(
            dietary_restrictions=["vegan"], cuisine_preference="italian", max_cook_time_minutes=20
        ),
        "stream_messages": [],
    }
    result = await search_recipes(state, _sequenced_runtime(mcp))

    assert [c for c in mcp.calls if c[1] == "search_recipes"] == mcp.calls[
        :1
    ]  # one search; the rest is the cookability probe
    assert result["recipe_candidates"] == [_recipe()]
    assert result["total_matched"] == 1
    assert result["search_exhausted"] is False
    assert not any("Dropping" in m or "raising" in m for m in result["stream_messages"])
    _, _, args = mcp.calls[0]
    assert args["dietary_filters"] == ["vegan"]


async def test_search_recipes_relaxes_in_order_and_never_touches_dietary() -> None:
    empty = ToolCallResult(success=True, data={"results": [], "total_matched": 0})
    success = ToolCallResult(success=True, data={"results": [_recipe()], "total_matched": 1})
    mcp = SequencedMCP({("recipe_engine", "search_recipes"): [empty, empty, empty, success]})
    state: MealSightState = {
        "unified_request": _unified(
            dietary_restrictions=["vegan"], cuisine_preference="italian", max_cook_time_minutes=20
        ),
        "context_signals": {"meal_type": "dinner"},
        "stream_messages": [],
    }
    result = await search_recipes(state, _sequenced_runtime(mcp))

    assert len(mcp.calls) == 4
    call_args = [args for _, _, args in mcp.calls]

    assert all(args["dietary_filters"] == ["vegan"] for args in call_args)

    # Order: meal_type (the system's own inferred guess) drops FIRST,
    # then cook time relaxes, then cuisine (the user's own stated
    # preference) drops LAST — the reordering this defect fix exists
    # for. "dinner" maps to the corpus's own real ["main", "side"]
    # values, never the literal string "dinner" (which is never an
    # actual stored meal_type).
    assert call_args[0]["cuisine"] == "italian"
    assert call_args[0]["max_cook_time"] == 20
    assert call_args[0]["meal_type"] == ["main", "side"]

    assert call_args[1]["cuisine"] == "italian"
    assert call_args[1]["max_cook_time"] == 20
    assert call_args[1]["meal_type"] is None

    assert call_args[2]["cuisine"] == "italian"
    assert call_args[2]["max_cook_time"] > 20
    assert call_args[2]["meal_type"] is None

    assert call_args[3]["cuisine"] is None
    assert call_args[3]["meal_type"] is None

    assert result["recipe_candidates"] == [_recipe()]
    assert result["search_exhausted"] is False
    assert any("Dropping the dinner meal-type guess" in m for m in result["stream_messages"])
    assert any("raising the cook-time limit" in m for m in result["stream_messages"])
    assert any("dropping the italian cuisine preference" in m for m in result["stream_messages"])

    # The stream messages themselves must report meal_type being
    # dropped BEFORE cuisine, matching the actual call order above.
    meal_type_msg_index = next(
        i for i, m in enumerate(result["stream_messages"]) if "dinner meal-type guess" in m
    )
    cuisine_msg_index = next(
        i for i, m in enumerate(result["stream_messages"]) if "italian cuisine preference" in m
    )
    assert meal_type_msg_index < cuisine_msg_index


async def test_search_recipes_drops_the_meal_type_filter_when_it_leaves_too_thin_a_pool() -> None:
    thin = ToolCallResult(success=True, data={"results": [_recipe()], "total_matched": 7})
    wide = ToolCallResult(success=True, data={"results": [_recipe(), _recipe()], "total_matched": 243})
    mcp = SequencedMCP({("recipe_engine", "search_recipes"): [thin, wide]})
    state: MealSightState = {
        "unified_request": _unified(),
        "context_signals": {"meal_type": "breakfast"},
        "stream_messages": [],
    }

    result = await search_recipes(state, _sequenced_runtime(mcp))

    first, second = (args for _, _, args in mcp.calls)
    assert first["meal_type"] == ["breakfast"]
    assert second["meal_type"] is None
    assert result["total_matched"] == 243
    assert any("Only 7 breakfast-appropriate recipe(s) exist" in m for m in result["stream_messages"])


async def test_search_recipes_keeps_the_meal_type_filter_when_the_pool_is_large_enough() -> None:
    full = ToolCallResult(success=True, data={"results": [_recipe()], "total_matched": 179})
    mcp = SequencedMCP({("recipe_engine", "search_recipes"): [full]})
    state: MealSightState = {
        "unified_request": _unified(),
        "context_signals": {"meal_type": "dinner"},
        "stream_messages": [],
    }

    await search_recipes(state, _sequenced_runtime(mcp))

    assert [c for c in mcp.calls if c[1] == "search_recipes"] == mcp.calls[
        :1
    ]  # one search; the rest is the cookability probe
    assert mcp.calls[0][2]["meal_type"] == ["main", "side"]


async def test_search_recipes_translates_hyphenated_dietary_restrictions_to_corpus_tags() -> None:
    # Real defect, found while building eval/dimension2: unified_
    # request.dietary_restrictions is normalized onto DIETARY_
    # RESTRICTION_VOCABULARY's own hyphenated spelling ("gluten-free",
    # "dairy-free", "nut-free"), but recipes.dietary_tags uses an
    # underscore ("gluten_free", ...) — passed straight through, this
    # matched 0 of 250 real recipes for any of the three; translating
    # the separator here is the fix.
    success = ToolCallResult(success=True, data={"results": [_recipe()], "total_matched": 1})
    mcp = SequencedMCP({("recipe_engine", "search_recipes"): [success]})
    state: MealSightState = {
        "unified_request": _unified(dietary_restrictions=["vegan", "gluten-free", "dairy-free", "nut-free"]),
        "context_signals": {},
        "stream_messages": [],
    }

    await search_recipes(state, _sequenced_runtime(mcp))

    call_args = mcp.calls[0][2]
    assert call_args["dietary_filters"] == ["vegan", "gluten_free", "dairy_free", "nut_free"]


async def test_search_recipes_zero_after_full_relaxation_marks_exhausted() -> None:
    empty = ToolCallResult(success=True, data={"results": [], "total_matched": 0})
    mcp = SequencedMCP({("recipe_engine", "search_recipes"): [empty, empty, empty, empty]})
    state: MealSightState = {
        "unified_request": _unified(
            dietary_restrictions=["vegan", "gluten-free"],
            cuisine_preference="italian",
            max_cook_time_minutes=20,
        ),
        "context_signals": {"meal_type": "dinner"},
        "stream_messages": [],
    }
    result = await search_recipes(state, _sequenced_runtime(mcp))

    assert result["recipe_candidates"] == []
    assert result["total_matched"] == 0
    assert result["search_exhausted"] is True
    assert any("kept throughout" in m for m in result["stream_messages"])
    # Translated to the recipe corpus's own underscore-separated tag
    # vocabulary before being sent to search_recipes — see search_
    # recipes.py's own module-level comment for the real defect this
    # translation fixes (dietary_filters=["gluten-free"] matched 0 of
    # 250 real recipes; ["gluten_free"] matched 117).
    assert all(args["dietary_filters"] == ["vegan", "gluten_free"] for _, _, args in mcp.calls)


async def test_search_recipes_skips_when_terminal() -> None:
    mcp = SequencedMCP()
    result = await search_recipes({"terminal": True, "stream_messages": []}, _sequenced_runtime(mcp))
    assert mcp.calls == []
    assert len(result["stream_messages"]) == 1


# --------------------------------------------------------------------
# match_rank
# --------------------------------------------------------------------


class RecipeAwareMCP:
    """Fake MCP for match_rank: responses depend on the specific
    recipe_id in the call arguments, not just (server, tool), since
    match_rank calls the same tool once per candidate recipe."""

    def __init__(
        self,
        match_ingredients: dict[str, dict[str, Any]] | None = None,
        check_repetition: dict[str, dict[str, Any]] | None = None,
        nutrition: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._match_ingredients = match_ingredients or {}
        self._check_repetition = check_repetition or {}
        self._nutrition = nutrition or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_tool(
        self, server: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        arguments = arguments or {}
        self.calls.append((server, tool_name, arguments))
        recipe_id = str(arguments.get("recipe_id"))
        data: dict[str, Any] | None
        if tool_name == "match_ingredients":
            data = self._match_ingredients.get(recipe_id)
        elif tool_name == "check_repetition":
            data = self._check_repetition.get(recipe_id)
        elif tool_name == "calculate_nutrition":
            data = self._nutrition.get(recipe_id)
        else:
            data = None
        if data is None:
            return ToolCallResult(success=False, error="unconfigured")
        return ToolCallResult(success=True, data=data)


def _match_data(
    match_score: float,
    matched_items: list[dict[str, Any]] | None = None,
    critical_missing: list[str] | None = None,
    can_cook: bool = True,
) -> dict[str, Any]:
    return {
        "match_score": match_score,
        "can_cook": can_cook,
        "matched_items": matched_items or [],
        "substitutable_items": [],
        "partial_matches": [],
        "missing_items": [],
        "critical_missing": critical_missing or [],
        "summary": "x",
    }


def _repetition_data(score: float = 0.0) -> dict[str, Any]:
    return {"repetition_score": score, "reason": "x", "recommendation": "acceptable", "last_cooked": None}


async def test_match_rank_orders_by_composite_score() -> None:
    mcp = RecipeAwareMCP(
        match_ingredients={
            "r_high": _match_data(0.9),
            "r_low": _match_data(0.3),
        },
        check_repetition={
            "r_high": _repetition_data(),
            "r_low": _repetition_data(),
        },
        nutrition={"r_high": {"totals": {}}, "r_low": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("r_low"), _recipe("r_high")],
        "unified_request": _unified(
            available_ingredients=[AvailableIngredient(name="onion", verified=True, source="vision")]
        ),
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))

    ids = [r["recipe_id"] for r in result["matched_recipes"]]
    assert ids[0] == "r_high"
    assert ids[1] == "r_low"


async def test_match_rank_does_not_offer_long_expired_pantry_items_as_ingredients() -> None:
    mcp = RecipeAwareMCP(
        match_ingredients={"r1": _match_data(0.5)},
        check_repetition={"r1": _repetition_data()},
        nutrition={"r1": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("r1")],
        "pantry_items": [
            {"name": "rice", "days_remaining": 5},
            {"name": "banana", "days_remaining": -48},  # long expired: waste, not an ingredient
            {"name": "egg", "days_remaining": -1},  # inside the grace window: still food
            {"name": "salt", "days_remaining": None},  # unknown expiry: left alone
        ],
        "unified_request": _unified(),
        "stream_messages": [],
    }

    await match_rank(state, _fake_runtime(mcp))

    sent = [args["available_ingredients"] for _, tool, args in mcp.calls if tool == "match_ingredients"]
    assert sent == [["rice", "egg", "salt"]]


async def test_match_rank_expiring_ingredient_recipe_ranks_above_equivalent() -> None:
    mcp = RecipeAwareMCP(
        match_ingredients={
            "uses_expiring": _match_data(0.5, matched_items=[{"name": "spinach"}]),
            "no_expiring": _match_data(0.5, matched_items=[{"name": "onion"}]),
        },
        check_repetition={
            "uses_expiring": _repetition_data(),
            "no_expiring": _repetition_data(),
        },
        nutrition={"uses_expiring": {"totals": {}}, "no_expiring": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("no_expiring"), _recipe("uses_expiring")],
        "unified_request": _unified(
            available_ingredients=[
                AvailableIngredient(name="spinach", verified=True, source="vision"),
                AvailableIngredient(name="onion", verified=True, source="vision"),
            ]
        ),
        "expiring_items": [{"name": "spinach", "days_remaining": 1}],
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))

    ids = [r["recipe_id"] for r in result["matched_recipes"]]
    assert ids[0] == "uses_expiring"
    assert result["matched_recipes"][0]["uses_expiring_ingredient"] is True


async def test_match_rank_calls_nutrition_for_top_3_only() -> None:
    match_scores = {"r1": 0.9, "r2": 0.8, "r3": 0.7, "r4": 0.6, "r5": 0.5}
    mcp = RecipeAwareMCP(
        match_ingredients={rid: _match_data(score) for rid, score in match_scores.items()},
        check_repetition={rid: _repetition_data() for rid in match_scores},
        nutrition={rid: {"totals": {}} for rid in match_scores},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe(rid) for rid in match_scores],
        "unified_request": _unified(),
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))

    nutrition_calls = [args["recipe_id"] for server, tool, args in mcp.calls if tool == "calculate_nutrition"]
    assert len(nutrition_calls) == 3
    assert set(nutrition_calls) == {"r1", "r2", "r3"}

    with_nutrition = [r["recipe_id"] for r in result["matched_recipes"] if "nutrition_info" in r]
    assert set(with_nutrition) == {"r1", "r2", "r3"}


async def test_match_rank_emits_recipe_match_per_candidate() -> None:
    mcp = RecipeAwareMCP(
        match_ingredients={
            "r_high": _match_data(0.9),
            "r_low": _match_data(0.3),
        },
        check_repetition={
            "r_high": _repetition_data(),
            "r_low": _repetition_data(),
        },
        nutrition={"r_high": {"totals": {}}, "r_low": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("r_low"), _recipe("r_high")],
        "unified_request": _unified(),
        "stream_messages": [],
    }
    stream = FakeStream()
    await match_rank(state, _fake_runtime_with_stream(mcp, stream))

    recipe_match_ids = {
        fields["recipe_id"] for event_type, fields in stream.events if event_type == "recipe_match"
    }
    assert recipe_match_ids == {"r_low", "r_high"}


async def test_match_rank_skips_when_terminal() -> None:
    mcp = RecipeAwareMCP()
    await match_rank({"terminal": True, "stream_messages": []}, _fake_runtime(mcp))
    assert mcp.calls == []


async def test_match_rank_handles_no_candidates() -> None:
    mcp = RecipeAwareMCP()
    result = await match_rank(
        {"recipe_candidates": [], "unified_request": _unified(), "stream_messages": []}, _fake_runtime(mcp)
    )
    assert result["matched_recipes"] == []
    assert mcp.calls == []


async def test_match_rank_uses_persisted_pantry_not_just_vision_verified() -> None:
    # "green onion" is only in the persisted pantry (state["pantry_items"],
    # from update_pantry's own get_pantry read-back) — NOT in this run's
    # own vision-verified unified_request.available_ingredients. Before the
    # fix, match_rank only ever passed the latter to match_ingredients, so
    # anything seen in an earlier run's photo was invisible to ranking.
    mcp = RecipeAwareMCP(match_ingredients={"r1": _match_data(0.5)})
    state: MealSightState = {
        "recipe_candidates": [_recipe("r1")],
        "pantry_items": [{"name": "green onion"}, {"name": "onion"}],
        "unified_request": _unified(
            available_ingredients=[AvailableIngredient(name="onion", verified=True, source="vision")]
        ),
        "stream_messages": [],
    }
    await match_rank(state, _fake_runtime(mcp))

    match_call_args = next(args for _, tool, args in mcp.calls if tool == "match_ingredients")
    assert "green onion" in match_call_args["available_ingredients"]
    assert "onion" in match_call_args["available_ingredients"]


async def test_match_rank_includes_unverified_mentions_alongside_pantry() -> None:
    # An ingredient only ever mentioned in speech/text (never seen, so
    # never written to the pantry) is still usable — just tracked
    # separately once matched (unverified_ingredient_matches).
    mcp = RecipeAwareMCP(match_ingredients={"r1": _match_data(0.5, matched_items=[{"name": "saffron"}])})
    state: MealSightState = {
        "recipe_candidates": [_recipe("r1")],
        "pantry_items": [{"name": "onion"}],
        "unified_request": _unified(
            available_ingredients=[
                AvailableIngredient(name="onion", verified=True, source="vision"),
                AvailableIngredient(name="saffron", verified=False, source="audio"),
            ]
        ),
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))

    match_call_args = next(args for _, tool, args in mcp.calls if tool == "match_ingredients")
    assert "saffron" in match_call_args["available_ingredients"]
    assert result["matched_recipes"][0]["unverified_ingredient_matches"] == ["saffron"]


async def test_match_rank_critical_missing_never_outranks_recipe_without() -> None:
    # Regression case from the real diagnosis run: Coq au vin
    # (critical_missing=['bacon'], match_score 0.0, but its matched_items
    # still include the run's expiring "chicken thigh") used to composite
    # to 0.225 under the old flat freshness/cuisine bonus — beating
    # Baingan Bharta (critical_missing=[], match_score 0.1111, no bonus)
    # at 0.14166, even though Baingan Bharta is strictly more cookable.
    mcp = RecipeAwareMCP(
        match_ingredients={
            "coq_au_vin": _match_data(
                0.0,
                matched_items=[{"name": "chicken thigh"}, {"name": "butter"}],
                critical_missing=["bacon"],
                can_cook=False,
            ),
            "baingan_bharta": _match_data(0.1111, matched_items=[{"name": "onion"}], can_cook=False),
        },
        check_repetition={
            "coq_au_vin": _repetition_data(),
            "baingan_bharta": _repetition_data(),
        },
        nutrition={"coq_au_vin": {"totals": {}}, "baingan_bharta": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("coq_au_vin"), _recipe("baingan_bharta")],
        "pantry_items": [{"name": "onion"}, {"name": "butter"}, {"name": "chicken thigh"}],
        "unified_request": _unified(),
        "expiring_items": [{"name": "chicken thigh", "days_remaining": 1}],
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))

    ranked = {r["recipe_id"]: r for r in result["matched_recipes"]}
    assert ranked["baingan_bharta"]["composite_score"] > ranked["coq_au_vin"]["composite_score"]
    assert result["matched_recipes"][0]["recipe_id"] == "baingan_bharta"


# --------------------------------------------------------------------
# reason
# --------------------------------------------------------------------


def _decision(
    chosen_recipe_id: str,
    chosen_because: list[str] | None = None,
    gave_up: list[str] | None = None,
    runner_up_id: str | None = None,
    variety_note: str | None = None,
    taste_note: str | None = None,
) -> RecipeDecision:
    return RecipeDecision(
        chosen_recipe_id=chosen_recipe_id,
        chosen_because=chosen_because if chosen_because is not None else ["cookable_now"],  # type: ignore[arg-type]
        gave_up=gave_up or [],  # type: ignore[arg-type]
        runner_up_id=runner_up_id,
        variety_note=variety_note,
        taste_note=taste_note,
    )


class FakeProvider:
    def __init__(self, decision: RecipeDecision) -> None:
        self._decision = decision

    async def complete_json(
        self, prompt: str, schema: type[BaseModel], model_id: str, **kwargs: object
    ) -> Any:
        return self._decision


async def test_reason_falls_back_when_model_returns_invalid_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(_decision("nonexistent")))

    state: MealSightState = {
        "unified_request": _unified(),
        "matched_recipes": [
            {
                "recipe_id": "top",
                "name": "Top Recipe",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.9,
                "can_cook": True,
            },
            {
                "recipe_id": "second",
                "name": "Second",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.5,
                "can_cook": True,
            },
        ],
        "stream_messages": [],
    }
    result = await reason(state, _runtime(FakeMCP()))

    assert result["top_recommendation"]["recipe_id"] == "top"
    assert result["top_recommendation"]["invalid_model_choice"] is True


async def test_reason_accepts_a_valid_model_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(_decision("second")))

    state: MealSightState = {
        "unified_request": _unified(),
        "matched_recipes": [
            {
                "recipe_id": "top",
                "name": "Top",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.9,
                "can_cook": True,
            },
            {
                "recipe_id": "second",
                "name": "Second",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.5,
                "can_cook": True,
            },
        ],
        "stream_messages": [],
    }
    result = await reason(state, _runtime(FakeMCP()))

    assert result["top_recommendation"]["recipe_id"] == "second"
    assert result["top_recommendation"]["invalid_model_choice"] is False


async def test_reason_emits_recommendation_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(_decision("second")))

    state: MealSightState = {
        "unified_request": _unified(),
        "matched_recipes": [
            {
                "recipe_id": "top",
                "name": "Top",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.9,
                "can_cook": True,
            },
            {
                "recipe_id": "second",
                "name": "Second",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.5,
                "can_cook": True,
            },
        ],
        "stream_messages": [],
    }
    stream = FakeStream()
    await reason(state, _runtime_with_stream(FakeMCP(), stream))

    recommendation_events = [fields for event_type, fields in stream.events if event_type == "recommendation"]
    assert len(recommendation_events) == 1
    assert recommendation_events[0]["recipe_id"] == "second"
    assert recommendation_events[0]["available"] is True


async def test_reason_handles_no_candidates_without_calling_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _exploding_provider() -> Any:
        raise AssertionError("get_text_provider should not be called when search_exhausted")

    monkeypatch.setattr(reason_module, "get_text_provider", _exploding_provider)

    state: MealSightState = {
        "search_exhausted": True,
        "unified_request": _unified(dietary_restrictions=["vegan"]),
        "stream_messages": [],
    }
    result = await reason(state, _runtime(FakeMCP()))

    assert result["top_recommendation"]["available"] is False
    assert "vegan" in result["top_recommendation"]["explanation"]


async def test_reason_explains_instead_of_recommending_when_nothing_cookable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _exploding_provider() -> Any:
        raise AssertionError("get_text_provider should not be called when nothing is cookable")

    monkeypatch.setattr(reason_module, "get_text_provider", _exploding_provider)

    state: MealSightState = {
        "unified_request": _unified(),
        "matched_recipes": [
            {
                "recipe_id": "top",
                "name": "Top Recipe",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.3,
                "can_cook": False,
                "missing_items": [{"name": "garlic"}, {"name": "tomato"}],
            },
            {
                "recipe_id": "second",
                "name": "Second",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.2,
                "can_cook": False,
                "missing_items": [{"name": "basil"}],
            },
        ],
        "stream_messages": [],
    }
    result = await reason(state, _runtime(FakeMCP()))

    assert result["top_recommendation"]["available"] is False
    assert "garlic" in result["top_recommendation"]["explanation"]
    assert "tomato" in result["top_recommendation"]["explanation"]


async def test_reason_prefers_cookable_candidate_over_uncookable_model_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(_decision("top")))

    state: MealSightState = {
        "unified_request": _unified(),
        "matched_recipes": [
            {
                "recipe_id": "top",
                "name": "Top Recipe",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.9,
                "can_cook": False,
            },
            {
                "recipe_id": "second",
                "name": "Second",
                "cuisine": "italian",
                "cook_time_minutes": 20,
                "match_score": 0.5,
                "can_cook": True,
            },
        ],
        "stream_messages": [],
    }
    result = await reason(state, _runtime(FakeMCP()))

    assert result["top_recommendation"]["recipe_id"] == "second"
    assert result["top_recommendation"]["overrode_uncookable_choice"] is True
    assert result["top_recommendation"]["model_chosen_recipe_id"] == "top"


def _reason_state(**overrides: Any) -> MealSightState:
    state: MealSightState = {
        "unified_request": _unified(
            max_cook_time_minutes=30, cuisine_preference="Indian", mood_or_preference="cozy"
        ),
        "matched_recipes": [
            _candidate(recipe_id="kumpir", name="Kumpir", cook_time_minutes=45),
            _candidate(recipe_id="other", name="Other", cook_time_minutes=20, match_score=0.4),
        ],
        "expiring_items": [{"name": "onion", "days_remaining": -2}],
        "waste_candidates": [{"name": "potatoes", "days_overdue": 30}],
        "user_profile": {"cuisine_preferences": {"mexican": 0.7}},
        "meal_history": [{"recipe_name": "Pasta"}],
        "context_signals": {"meal_type": "lunch", "complexity_suggestion": "Friday: room for more."},
        "stream_messages": [],
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


async def test_reason_renders_factual_dimensions_from_data_and_keeps_the_model_to_judgment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The model's free text is deliberately nonsense about facts; none of it
    # may reach the four factual dimensions.
    decision = _decision(
        "kumpir", ["cookable_now", "time", "mood"], gave_up=["cuisine"], runner_up_id="other"
    )
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(decision))

    result = await reason(_reason_state(), _runtime(FakeMCP()))

    top = result["top_recommendation"]
    reasoning = top["reasoning"]
    assert top["recipe_id"] == "kumpir"
    # "time" is dropped: the 45-minute recipe is over the 30-minute limit, so the
    # data does not support it. "mood" is a pure judgment, so it is kept.
    expected = (
        "Kumpir was chosen for being cookable with what you have and matching the mood you described. "
        "The compromise is matching your cuisine preference. "
        "None of the candidates is Indian cuisine, so that request could not be met. "
        "The closest alternative was Other."
    )
    assert reasoning["overall_summary"] == top["overall_summary"] == expected
    assert "its cook time" not in top["overall_summary"]
    ingredients = reasoning["ingredient_match_reasoning"]["reasoning"]
    assert "You have 2 of this recipe's 3 ingredients: Potatoes, Onion." in ingredients
    assert "Missing: red pepper (optional)." in ingredients
    fresh = reasoning["freshness_reasoning"]["reasoning"]
    assert "Onion (expired 2 day(s) ago)" in fresh
    assert "Check before cooking" in fresh and "Potatoes (expired 30 day(s) ago)" in fresh
    context = reasoning["context_reasoning"]["reasoning"]
    assert "EXCEEDS your 30-minute limit by 15 min" in context
    assert "You asked for Indian cuisine; this recipe is Turkish, so that request is not met." in context
    factual = ("ingredient_match_reasoning", "freshness_reasoning", "context_reasoning")
    assert {reasoning[k]["source"] for k in factual} == {"data"}
    assert reasoning["nutrition_reasoning"]["applies"] is False


async def test_variety_and_taste_are_rendered_from_data_with_no_model_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The decision schema has no free-text field at all, so nothing the model
    # writes can reach these two dimensions; a stray extra key is ignored.
    decision = RecipeDecision.model_validate(
        {
            "chosen_recipe_id": "kumpir",
            "taste_note": "The user dislikes Turkish food.",
            "variety_note": "null",
        }
    )
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(decision))

    with_data = (await reason(_reason_state(), _runtime(FakeMCP())))["top_recommendation"]["reasoning"]
    no_data = (await reason(_reason_state(meal_history=[], user_profile={}), _runtime(FakeMCP())))[
        "top_recommendation"
    ]["reasoning"]

    assert with_data["variety_reasoning"]["reasoning"].startswith("Recent meals: Pasta.")
    assert with_data["taste_reasoning"]["reasoning"] == (
        "Cuisine preference scores on file: mexican 0.7. This recipe is Turkish, which has no score on file."
    )
    for dimension in ("variety_reasoning", "taste_reasoning"):
        assert with_data[dimension]["source"] == "data"
        text = with_data[dimension]["reasoning"]
        assert "dislikes" not in text and "null" not in text
    assert no_data["variety_reasoning"]["applies"] is False
    assert no_data["taste_reasoning"]["applies"] is False


async def test_priorities_the_data_contradicts_are_dropped_and_unmet_requests_are_stated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Claims the model might make that the data contradicts: freshness (no
    # expiring ingredient in this recipe), cuisine (Turkish, Indian asked),
    # and a gave_up that is actually satisfied (cookable_now).
    decision = _decision("kumpir", ["freshness", "cuisine"], gave_up=["cookable_now"])
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(decision))
    state = _reason_state(expiring_items=[{"name": "chicken", "days_remaining": 2}])

    top = (await reason(state, _runtime(FakeMCP())))["top_recommendation"]

    summary = top["overall_summary"]
    assert top["available"] is True and top["recipe_id"] == "kumpir"
    assert summary.startswith("Kumpir is the best available match.")
    assert "pantry items near the end" not in summary
    assert "compromise" not in summary
    assert "None of the candidates is Indian cuisine, so that request could not be met." in summary


async def test_a_null_choice_uses_the_top_cookable_candidate_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = RecipeDecision(chosen_recipe_id=None, chosen_because=["cookable_now"])
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(decision))
    state = _reason_state(
        matched_recipes=[
            _candidate(recipe_id="uncookable", name="Nope", can_cook=False),
            _candidate(recipe_id="cookable", name="Yes"),
        ]
    )

    top = (await reason(state, _runtime(FakeMCP())))["top_recommendation"]

    assert top["available"] is True
    assert top["recipe_id"] == "cookable"
    assert top["invalid_model_choice"] is False


def test_the_decision_schema_accepts_partial_and_unknown_values_without_failing() -> None:
    # What an 8B model actually sends: missing slots, invented priorities.
    decision = RecipeDecision.model_validate(
        {"chosen_recipe_id": "a", "chosen_because": ["vibes", "cuisine"]}
    )

    assert decision.gave_up == [] and decision.runner_up_id is None
    assert "vibes" not in reason_module.PRIORITY_PHRASES


async def test_unknown_priorities_are_ignored_when_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = _decision("kumpir", ["vibes", "cookable_now"], gave_up=["luck"])
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(decision))

    top = (await reason(_reason_state(), _runtime(FakeMCP())))["top_recommendation"]

    assert top["overall_summary"].startswith("Kumpir was chosen for being cookable with what you have.")
    assert "vibes" not in top["overall_summary"] and "luck" not in top["overall_summary"]


async def test_priorities_with_no_data_behind_them_are_never_stated(monkeypatch: pytest.MonkeyPatch) -> None:
    # No cuisine/protein/mood request, no meal history, no taste profile, no
    # nutrition figures, no expiring items: none of these can honestly be
    # called a benefit or a compromise.
    decision = _decision(
        "kumpir",
        ["cookable_now", "variety", "taste", "mood", "nutrition", "freshness"],
        gave_up=["cuisine", "protein", "variety", "taste"],
    )
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(decision))
    state = _reason_state(
        unified_request=_unified(max_cook_time_minutes=30),
        meal_history=[],
        user_profile={},
        expiring_items=[],
        waste_candidates=[],
    )

    top = (await reason(state, _runtime(FakeMCP())))["top_recommendation"]

    assert top["overall_summary"] == "Kumpir was chosen for being cookable with what you have."


async def test_taste_is_supported_only_by_a_real_preference_score(monkeypatch: pytest.MonkeyPatch) -> None:
    liked = _decision("kumpir", ["taste"])
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(liked))
    scored = _reason_state(user_profile={"cuisine_preferences": {"turkish": 0.9}})
    unscored = _reason_state(user_profile={"cuisine_preferences": {"mexican": 0.7}})

    with_score = (await reason(scored, _runtime(FakeMCP())))["top_recommendation"]["overall_summary"]
    without_score = (await reason(unscored, _runtime(FakeMCP())))["top_recommendation"]["overall_summary"]

    assert "matching your taste preferences" in with_score
    assert "taste" not in without_score


async def test_a_runner_up_that_is_not_a_candidate_or_is_the_choice_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for runner_up in ("kumpir", "nonexistent"):
        decision = _decision("kumpir", ["cookable_now"], runner_up_id=runner_up)
        monkeypatch.setattr(reason_module, "get_text_provider", lambda d=decision: FakeProvider(d))  # type: ignore[misc]

        top = (await reason(_reason_state(), _runtime(FakeMCP())))["top_recommendation"]

        assert "closest alternative" not in top["overall_summary"]


async def test_override_reasoning_describes_the_recipe_actually_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reason_module, "get_text_provider", lambda: FakeProvider(_decision("kumpir")))
    state = _reason_state(
        matched_recipes=[
            _candidate(recipe_id="kumpir", name="Kumpir", can_cook=False),
            _candidate(
                recipe_id="other",
                name="Other",
                cook_time_minutes=20,
                matched_items=[{"name": "Rice", "importance": "critical"}],
                missing_items=[],
            ),
        ]
    )

    top = (await reason(state, _runtime(FakeMCP())))["top_recommendation"]

    assert top["recipe_id"] == "other"
    assert top["reasoning"]["chosen_recipe_id"] == "other"
    ingredients = top["reasoning"]["ingredient_match_reasoning"]["reasoning"]
    assert "You have 1 of this recipe's 1 ingredients: Rice." in ingredients


def test_reason_prompt_includes_can_cook_per_candidate() -> None:
    candidates: list[dict[str, Any]] = [
        {
            "recipe_id": "r1",
            "name": "Cookable Recipe",
            "cuisine": "italian",
            "cook_time_minutes": 20,
            "match_score": 0.8,
            "can_cook": True,
        },
        {
            "recipe_id": "r2",
            "name": "Uncookable Recipe",
            "cuisine": "italian",
            "cook_time_minutes": 20,
            "match_score": 0.1,
            "can_cook": False,
        },
    ]
    prompt = reason_module.build_prompt(_unified(), candidates, [], {}, [], {})

    assert "can_cook: True" in prompt
    assert "can_cook: False" in prompt


def _candidate(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "recipe_id": "r1",
        "name": "Kumpir",
        "cuisine": "Turkish",
        "cook_time_minutes": 25,
        "match_score": 0.5,
        "can_cook": True,
        "matched_items": [
            {"name": "Potatoes", "importance": "critical"},
            {"name": "Onion", "importance": "important"},
        ],
        "missing_items": [{"name": "red pepper", "importance": "optional"}],
        "partial_matches": [],
        "substitutable_items": [],
    }
    base.update(overrides)
    return base


def test_expiry_is_rendered_in_words_never_as_a_signed_number() -> None:
    expiring = [
        {"name": "chicken", "days_remaining": -49},
        {"name": "milk", "days_remaining": 0},
        {"name": "yogurt", "days_remaining": 3},
    ]
    prompt = reason_module.build_prompt(_unified(), [_candidate()], expiring, {}, [], {})

    assert "chicken: expired 49 day(s) ago" in prompt
    assert "milk: expires today" in prompt
    assert "yogurt: expires in 3 day(s)" in prompt
    assert "-49" not in prompt
    assert "day(s) left" not in prompt


def test_each_candidate_lists_its_own_ingredients_separately_from_the_pantry() -> None:
    expiring = [{"name": "onion", "days_remaining": -23}, {"name": "chicken", "days_remaining": 2}]
    prompt = reason_module.build_prompt(_unified(), [_candidate()], expiring, {}, [], {})

    block = prompt[prompt.index("===== Recipe id: r1 =====") : prompt.index("===== end of recipe r1 =====")]
    assert "THIS RECIPE'S OWN INGREDIENTS" in block
    assert "the user has: Potatoes, Onion" in block
    assert "red pepper (optional)" in block
    # Only the expiring item the recipe actually contains is named; chicken
    # is in the pantry's expiring list but not in this recipe.
    assert "Onion (expired 23 day(s) ago)" in block
    assert "chicken" not in block
    assert prompt.index("THE USER'S PANTRY") < prompt.index("CANDIDATE RECIPES")


def test_ingredient_dimension_explains_a_missing_item_that_is_only_missing_because_it_expired() -> None:
    from mealsight.agent.reasoning_facts import ingredient_match_dimension

    recipe = _candidate(
        matched_items=[{"name": "Egg", "importance": "critical"}],
        missing_items=[{"name": "banana", "importance": "important"}],
    )

    text = ingredient_match_dimension(recipe, {"banana": -48})["reasoning"]

    assert "Missing: banana (important)." in text
    assert "Not counted as on hand: your pantry lists banana (expired 48 day(s) ago)" in text


def test_recipe_with_no_expiring_ingredient_says_none() -> None:
    prompt = reason_module.build_prompt(
        _unified(), [_candidate()], [{"name": "chicken", "days_remaining": 2}], {}, [], {}
    )
    assert "expired or expiring pantry items this recipe uses: none" in prompt


def test_cook_time_is_compared_to_the_limit_in_code() -> None:
    unified = _unified(max_cook_time_minutes=30)
    over = reason_module.build_prompt(unified, [_candidate(cook_time_minutes=45)], [], {}, [], {})
    within = reason_module.build_prompt(unified, [_candidate(cook_time_minutes=25)], [], {}, [], {})

    assert "cook time: 45 min (EXCEEDS the 30-minute limit by 15 min" in over
    assert "cook time: 25 min (within the 30-minute limit)" in within


def test_nutrition_numbers_are_rendered_field_by_field() -> None:
    nutrition = {
        "servings": 2,
        "calories": 546.0,
        "protein_g": 10.6,
        "coverage_note": "Nutrition calculated from all 6 ingredients.",
    }
    prompt = reason_module.build_prompt(_unified(), [_candidate(nutrition_info=nutrition)], [], {}, [], {})

    assert "nutrition (per serving, at 2 serving(s)): calories 546.0 kcal, protein 10.6 g" in prompt


def test_system_prompt_limits_the_model_to_judgment() -> None:
    text = reason_module.SYSTEM_PROMPT
    assert "do NOT restate, summarize or recompute those facts" in text
    assert "not what any recipe contains" in text
    assert "EXCEEDS" in text
    assert "You always choose one" in text


async def test_reason_skips_when_terminal() -> None:
    result = await reason({"terminal": True, "stream_messages": []}, _runtime(FakeMCP()))
    assert "top_recommendation" not in result


def test_reason_prompt_excludes_full_recipe_steps() -> None:
    candidates: list[dict[str, Any]] = [
        {
            "recipe_id": "r1",
            "name": "Test Recipe",
            "cuisine": "italian",
            "cook_time_minutes": 20,
            "match_score": 0.8,
            "steps": ["Step 1: preheat the oven to 350F", "Step 2: mix everything together"],
            "ingredients": ["1 cup flour", "2 eggs"],
        }
    ]
    prompt = reason_module.build_prompt(_unified(), candidates, [], {}, [], {})

    assert "preheat the oven" not in prompt
    assert "1 cup flour" not in prompt
    assert "r1" in prompt


def test_reason_prompt_token_count_is_reasonable() -> None:
    candidates: list[dict[str, Any]] = [
        {
            "recipe_id": "r1",
            "name": "Test Recipe",
            "cuisine": "italian",
            "cook_time_minutes": 20,
            "match_score": 0.8,
        }
    ]
    prompt = reason_module.build_prompt(_unified(), candidates, [], {}, [], {})
    tokens = reason_module.prompt_token_count(prompt)
    assert tokens > 0
    assert tokens < 5000


def test_reason_prompt_includes_weather_when_present() -> None:
    candidates: list[dict[str, Any]] = [
        {
            "recipe_id": "r1",
            "name": "Chili",
            "cuisine": "american",
            "cook_time_minutes": 30,
            "match_score": 0.8,
        }
    ]
    context_signals = {
        "meal_type": "dinner",
        "complexity_suggestion": "Monday — a weeknight; favor something quick.",
        "context_notes": ["No cooking history recorded for Monday around this hour yet."],
        "temperature_f": 28.0,
        "conditions": "light snow",
        "mood_suggestion": "warm, hearty, comforting",
    }
    prompt = reason_module.build_prompt(_unified(), candidates, [], {}, [], context_signals)

    assert "28F" in prompt
    assert "light snow" in prompt
    assert "warm, hearty, comforting" in prompt


def test_reason_prompt_omits_weather_cleanly_when_absent() -> None:
    candidates: list[dict[str, Any]] = [
        {
            "recipe_id": "r1",
            "name": "Chili",
            "cuisine": "american",
            "cook_time_minutes": 30,
            "match_score": 0.8,
        }
    ]
    context_signals = {
        "meal_type": "dinner",
        "complexity_suggestion": "Monday — a weeknight; favor something quick.",
        "context_notes": ["No cooking history recorded for Monday around this hour yet."],
        "temperature_f": None,
        "conditions": None,
        "mood_suggestion": None,
    }
    prompt = reason_module.build_prompt(_unified(), candidates, [], {}, [], context_signals)

    assert "weather" not in prompt.lower()
    # The rest of the context dimension is completely unaffected by
    # weather's absence.
    assert "dinner" in prompt
    assert "Monday" in prompt


def test_reason_prompt_token_count_barely_changes_with_weather_present() -> None:
    candidates: list[dict[str, Any]] = [
        {
            "recipe_id": "r1",
            "name": "Chili",
            "cuisine": "american",
            "cook_time_minutes": 30,
            "match_score": 0.8,
        }
    ]
    without_weather = {
        "meal_type": "dinner",
        "complexity_suggestion": "quick",
        "context_notes": ["none"],
    }
    with_weather = {
        **without_weather,
        "temperature_f": 28.0,
        "conditions": "light snow",
        "mood_suggestion": "warm, hearty, comforting",
    }

    tokens_before = reason_module.prompt_token_count(
        reason_module.build_prompt(_unified(), candidates, [], {}, [], without_weather)
    )
    tokens_after = reason_module.prompt_token_count(
        reason_module.build_prompt(_unified(), candidates, [], {}, [], with_weather)
    )

    # The one-line weather addition costs a real but small handful of
    # tokens against the 375K TPM budget this prompt runs against, not a
    # step change in prompt size.
    assert tokens_after > tokens_before
    assert tokens_after - tokens_before < 60


# --------------------------------------------------------------------
# generate_output
# --------------------------------------------------------------------


def _recipe_detail(recipe_id: str = "r1", **kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": recipe_id,
        "name": "Test Recipe",
        "cuisine": "italian",
        "meal_type": "dinner",
        "cook_time_minutes": 20,
        "difficulty": "easy",
        "servings_base": 2,
        "dietary_tags": [],
        "ingredients": [
            {"name": "onion", "quantity": 1, "unit": "count", "importance": "important", "raw_measure": "1"}
        ],
        "steps": ["Chop the onion.", "Cook it."],
        "image_url": None,
    }
    base.update(kwargs)
    return base


def _scaled_recipe(recipe_id: str = "r1", target_servings: int = 2, **kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": recipe_id,
        "name": "Test Recipe",
        "original_servings": 2,
        "target_servings": target_servings,
        "scale_factor": target_servings / 2,
        "ingredients": [
            {"name": "onion", "quantity_display": "1", "unit": "count", "importance": "important"}
        ],
        "cook_time_minutes": 20,
        "cook_time_adjusted": False,
        "cook_time_note": None,
    }
    base.update(kwargs)
    return base


def _grocery_list(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 1,
        "status": "active",
        "created_at": "2026-01-01",
        "sections": [
            {
                "section": "produce",
                "items": [
                    {
                        "name": "garlic",
                        "quantities": [],
                        "needed_for": ["Test Recipe"],
                        "importance": "important",
                        "section": "produce",
                        "is_staple": False,
                        "verify_note": None,
                        "checked": False,
                    }
                ],
            }
        ],
    }
    base.update(kwargs)
    return base


async def test_generate_output_never_calls_remove_items() -> None:
    mcp = FakeMCP(
        {
            ("recipe_engine", "get_recipe"): ToolCallResult(success=True, data=_recipe_detail()),
            ("recipe_engine", "scale_recipe"): ToolCallResult(success=True, data=_scaled_recipe()),
            ("recipe_engine", "find_substitutions"): ToolCallResult(
                success=True,
                data={
                    "ingredient": "garlic",
                    "reason": "unavailable",
                    "suggestions": [],
                    "excluded_count": 0,
                },
            ),
            ("pantry_manager", "create_grocery_list"): ToolCallResult(success=True, data=_grocery_list()),
        }
    )
    state: MealSightState = {
        "top_recommendation": {"available": True, "recipe_id": "r1", "overall_summary": "Good pick."},
        "matched_recipes": [
            {
                "recipe_id": "r1",
                "name": "Test Recipe",
                "match_score": 0.9,
                "missing_items": [{"name": "garlic", "importance": "important"}],
                "substitutable_items": [],
                "nutrition_info": None,
            }
        ],
        "unified_request": _unified(servings=2),
        "stream_messages": [],
    }
    await generate_output(state, _runtime(mcp))

    called_tools = {tool for _, tool, _ in mcp.calls}
    assert "remove_items" not in called_tools


async def test_generate_output_no_cookable_recipe_produces_explanation_and_grocery_list() -> None:
    mcp = FakeMCP(
        {("pantry_manager", "create_grocery_list"): ToolCallResult(success=True, data=_grocery_list())}
    )
    state: MealSightState = {
        "top_recommendation": {"available": False, "explanation": "Nothing was cookable. Buy garlic."},
        "matched_recipes": [
            {
                "recipe_id": "closest",
                "name": "Closest Recipe",
                "missing_items": [{"name": "garlic", "importance": "important"}],
            }
        ],
        "stream_messages": [],
    }
    result = await generate_output(state, _runtime(mcp))

    assert "Nothing was cookable" in result["final_response"]
    assert "garlic" in result["final_response"]
    assert result["grocery_list"] == _grocery_list()
    called_tools = {tool for _, tool, _ in mcp.calls}
    assert "create_grocery_list" in called_tools
    assert "remove_items" not in called_tools


async def test_generate_output_applies_scaling_to_response() -> None:
    mcp = FakeMCP(
        {
            ("recipe_engine", "get_recipe"): ToolCallResult(success=True, data=_recipe_detail()),
            ("recipe_engine", "scale_recipe"): ToolCallResult(
                success=True, data=_scaled_recipe(target_servings=4)
            ),
        }
    )
    state: MealSightState = {
        "top_recommendation": {"available": True, "recipe_id": "r1", "overall_summary": "Great fit."},
        "matched_recipes": [
            {
                "recipe_id": "r1",
                "name": "Test Recipe",
                "match_score": 1.0,
                "missing_items": [],
                "substitutable_items": [],
            }
        ],
        "unified_request": _unified(servings=4),
        "stream_messages": [],
    }
    result = await generate_output(state, _runtime(mcp))

    assert result["scaled_recipe"]["target_servings"] == 4
    assert "for 4 servings" in result["final_response"]
    scale_call = next(args for _, tool, args in mcp.calls if tool == "scale_recipe")
    assert scale_call["target_servings"] == 4


async def test_generate_output_failure_still_yields_partial_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_find_matched_entry(matched_recipes: object, recipe_id: object) -> object:
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(generate_output_module, "_find_matched_entry", broken_find_matched_entry)

    mcp = FakeMCP()
    state: MealSightState = {
        "top_recommendation": {"available": True, "recipe_id": "r1", "overall_summary": "Great fit."},
        "matched_recipes": [{"recipe_id": "r1", "name": "Test Recipe"}],
        "stream_messages": [],
    }
    result = await generate_output(state, _runtime(mcp))

    assert result["final_response"]
    assert "Great fit." in result["final_response"]
    assert any("unexpectedly" in m for m in result["stream_messages"])


async def test_generate_output_skips_when_terminal() -> None:
    mcp = FakeMCP()
    result = await generate_output({"terminal": True, "stream_messages": []}, _runtime(mcp))
    assert mcp.calls == []
    assert len(result["stream_messages"]) == 1


async def test_generate_output_handles_no_recommendation() -> None:
    mcp = FakeMCP()
    result = await generate_output({"stream_messages": []}, _runtime(mcp))
    assert mcp.calls == []
    assert result["final_response"]


# --------------------------------------------------------------------
# record_outcome
# --------------------------------------------------------------------


async def test_record_outcome_never_calls_any_mcp_tool() -> None:
    result = await record_outcome({"stream_messages": []})
    assert len(result["stream_messages"]) == 1


async def test_record_outcome_skips_when_terminal() -> None:
    result = await record_outcome({"terminal": True, "stream_messages": []})
    assert len(result["stream_messages"]) == 1


# --------------------------------------------------------------------
# present
# --------------------------------------------------------------------


class FakeProviderWithLog:
    def __init__(self, call_log: list[dict[str, Any]]) -> None:
        self._call_log = call_log

    def get_call_log(self) -> list[dict[str, Any]]:
        return self._call_log


async def test_present_trace_contains_every_mcp_call() -> None:
    mcp = FakeMCP({("recipe_engine", "get_recipe"): ToolCallResult(success=True, data={"id": "r1"})})
    await mcp.call_tool("recipe_engine", "get_recipe", {"recipe_id": "r1"})
    await mcp.call_tool("pantry_manager", "get_pantry", {})

    state: MealSightState = {"stream_messages": [], "trace_id": "t1"}
    result = await present(state, _runtime(mcp))

    trace = result["processing_trace"][0]
    assert len(trace["mcp_calls"]) == 2
    assert {c["tool"] for c in trace["mcp_calls"]} == {"get_recipe", "get_pantry"}


async def test_present_filters_llm_calls_by_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    text_calls = [
        {
            "model_id": "ministral-8b-2512",
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "latency_ms": 500.0,
            "trace_id": "match",
        },
        {
            "model_id": "ministral-8b-2512",
            "prompt_tokens": 50,
            "completion_tokens": 10,
            "total_tokens": 60,
            "latency_ms": 300.0,
            "trace_id": "other",
        },
    ]
    monkeypatch.setattr(present_module, "get_text_provider", lambda: FakeProviderWithLog(text_calls))
    monkeypatch.setattr(present_module, "get_audio_provider", lambda: FakeProviderWithLog([]))

    mcp = FakeMCP()
    state: MealSightState = {"stream_messages": [], "trace_id": "match"}
    result = await present(state, _runtime(mcp))

    llm_calls = result["processing_trace"][0]["llm_calls"]
    assert len(llm_calls) == 1
    assert llm_calls[0]["trace_id"] == "match"


async def test_present_includes_ranking_table() -> None:
    mcp = FakeMCP()
    state: MealSightState = {
        "stream_messages": [],
        "matched_recipes": [
            {
                "recipe_id": "r1",
                "name": "Test Recipe",
                "match_score": 0.8,
                "composite_score": 0.5,
                "can_cook": True,
            }
        ],
    }
    result = await present(state, _runtime(mcp))
    assert result["processing_trace"][0]["ranking"] == [
        {
            "recipe_id": "r1",
            "name": "Test Recipe",
            "match_score": 0.8,
            "composite_score": 0.5,
            "can_cook": True,
        }
    ]


async def test_present_streams_completion_message_and_skips_when_terminal() -> None:
    mcp = FakeMCP()
    result = await present({"terminal": True, "stream_messages": []}, _runtime(mcp))
    assert len(result["stream_messages"]) == 1
    assert "processing_trace" not in result


# --------------------------------------------------------------------
# present: interaction_history recording
# --------------------------------------------------------------------


async def test_present_records_interaction_even_with_no_cookable_recipe() -> None:
    mcp = FakeMCP()
    state: MealSightState = {
        "stream_messages": [],
        "trace_id": "t1",
        "text_input": "something quick",
        "final_response": "Nothing cookable this run.",
        "matched_recipes": [
            {"recipe_id": "r1", "name": "Uncookable Thing", "match_score": 0.4, "can_cook": False}
        ],
        "top_recommendation": {"available": False, "explanation": "Nothing cookable this run."},
    }
    await present(state, _runtime(mcp))

    record_calls = [c for c in mcp.calls if c[:2] == ("user_intelligence", "record_interaction")]
    assert len(record_calls) == 1
    args = record_calls[0][2]
    assert args["recommended_recipe_id"] is None
    assert args["recommended_recipe_name"] is None
    assert args["any_cookable"] is False
    assert args["top_match_score"] == 0.4
    assert args["final_response"] == "Nothing cookable this run."


async def test_present_records_interaction_with_the_chosen_recipe_when_available() -> None:
    mcp = FakeMCP()
    state: MealSightState = {
        "stream_messages": [],
        "matched_recipes": [
            {"recipe_id": "r1", "name": "Cookable Thing", "match_score": 0.9, "can_cook": True}
        ],
        "top_recommendation": {"available": True, "recipe_id": "r1"},
        "final_response": "Make Cookable Thing.",
    }
    await present(state, _runtime(mcp))

    args = next(args for _, tool, args in mcp.calls if tool == "record_interaction")
    assert args["recommended_recipe_id"] == "r1"
    assert args["recommended_recipe_name"] == "Cookable Thing"
    assert args["any_cookable"] is True
    assert args["top_match_score"] == 0.9


async def test_present_records_interaction_from_raw_inputs_when_terminal() -> None:
    mcp = FakeMCP()
    state: MealSightState = {
        "terminal": True,
        "stream_messages": [],
        "image_bytes": b"not a real image",
        "terminal_reason": "No usable input.",
    }
    await present(state, _runtime(mcp))

    args = next(args for _, tool, args in mcp.calls if tool == "record_interaction")
    assert args["modalities"] == ["vision"]
    assert args["final_response"] == "No usable input."
    assert args["recommended_recipe_id"] is None
    assert args["any_cookable"] is False


async def test_present_never_stores_raw_media_bytes_in_the_interaction_record() -> None:
    mcp = FakeMCP()
    state: MealSightState = {
        "stream_messages": [],
        "image_bytes": b"\xff\xd8\xff totally real jpeg bytes",
        "audio_bytes": b"\x1a\x45\xdf\xa3 totally real webm bytes",
        "vision_result": VisionPerception(
            identified_items=[
                IdentifiedItem(
                    name="egg",
                    quantity=6.0,
                    unit="count",
                    category="protein",
                    freshness="fresh",
                    confidence="high",
                )
            ],
            total_items_found=1,
            photo_quality="good",
            notes=None,
        ),
        "audio_result": AudioPerception(
            raw_transcript="I have eggs",
            servings=None,
            max_cook_time_minutes=None,
            dietary_restrictions=[],
            cuisine_preference=None,
            avoid_ingredients=[],
            avoid_dishes=[],
            mood_or_preference=None,
            protein_preference=None,
            occasion=None,
            additional_context=None,
        ),
    }
    await present(state, _runtime(mcp))

    args = next(args for _, tool, args in mcp.calls if tool == "record_interaction")
    serialized = str(args)
    assert "\\xff\\xd8\\xff" not in serialized
    assert "totally real jpeg bytes" not in serialized
    assert "totally real webm bytes" not in serialized
    assert args["voice_transcript"] == "I have eggs"
    assert args["ingredients_summary"] == "Found 1 item(s): egg"


async def test_match_rank_excludes_recipes_with_avoided_ingredients_in_code() -> None:
    """avoid_ingredients is enforced here, not left to the reasoning model:
    'nut' must exclude a recipe whose ingredient is almonds."""
    mcp = RecipeAwareMCP(
        match_ingredients={
            "r_nutty": _match_data(0.95, matched_items=[{"name": "almonds"}]),
            "r_clean": _match_data(0.4, matched_items=[{"name": "rice"}]),
        },
        check_repetition={"r_nutty": _repetition_data(), "r_clean": _repetition_data()},
        nutrition={"r_nutty": {"totals": {}}, "r_clean": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("r_nutty"), _recipe("r_clean")],
        "unified_request": _unified(avoid_ingredients=["nut"]),
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))

    assert [r["recipe_id"] for r in result["matched_recipes"]] == ["r_clean"]
    assert any("asked to avoid" in m for m in result["stream_messages"])


async def test_match_rank_returns_nothing_when_every_candidate_is_avoided() -> None:
    mcp = RecipeAwareMCP(
        match_ingredients={"r_nutty": _match_data(0.95, matched_items=[{"name": "walnuts"}])},
        check_repetition={"r_nutty": _repetition_data()},
        nutrition={"r_nutty": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("r_nutty")],
        "unified_request": _unified(avoid_ingredients=["nut"]),
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))
    assert result["matched_recipes"] == []


async def test_search_relaxes_cuisine_when_nothing_cookable_not_only_when_empty() -> None:
    """A non-empty result set nothing in the pantry can make must trigger
    relaxation of the soft preference (cuisine), while the dietary filter
    and the user's stated cook time stay in force."""
    italian = {
        "results": [{"id": "r_it", "name": "Pasta", "cuisine": "Italian", "cook_time_minutes": 20}],
        "total_matched": 1,
    }
    other = {
        "results": [{"id": "r_ok", "name": "Soup", "cuisine": "British", "cook_time_minutes": 20}],
        "total_matched": 1,
    }
    mcp = SequencedMCP(
        {
            ("recipe_engine", "search_recipes"): [
                ToolCallResult(success=True, data=italian),
                ToolCallResult(success=True, data=other),
            ],
            ("recipe_engine", "match_ingredients"): [
                ToolCallResult(
                    success=True, data={"can_cook": False, "matched_items": [], "missing_items": []}
                ),
                ToolCallResult(
                    success=True,
                    data={"can_cook": True, "matched_items": [{"name": "leek"}], "missing_items": []},
                ),
            ],
        }
    )
    state: MealSightState = {
        "unified_request": _unified(
            dietary_restrictions=["vegetarian"], cuisine_preference="Italian", max_cook_time_minutes=20
        ),
        "context_signals": {},
        "stream_messages": [],
    }
    result = await search_recipes(state, _sequenced_runtime(mcp))

    searches = [c[2] for c in mcp.calls if c[1] == "search_recipes"]
    assert searches[0]["cuisine"] == "Italian"
    assert searches[1]["cuisine"] is None
    assert all(s["dietary_filters"] == ["vegetarian"] and s["max_cook_time"] == 20 for s in searches)
    assert [r["id"] for r in result["recipe_candidates"]] == ["r_ok"]
    assert any("beyond Italian" in m for m in result["stream_messages"])


async def test_profile_default_cook_time_is_not_sent_to_search_as_a_filter() -> None:
    mcp = SequencedMCP(
        {
            ("recipe_engine", "search_recipes"): [
                ToolCallResult(success=True, data={"results": [{"id": "r"}], "total_matched": 1})
            ]
        }
    )
    state: MealSightState = {
        "unified_request": _unified(max_cook_time_minutes=30, max_cook_time_is_default=True),
        "context_signals": {},
        "stream_messages": [],
    }
    await search_recipes(state, _sequenced_runtime(mcp))
    assert mcp.calls[0][2]["max_cook_time"] is None


async def test_match_rank_default_time_nudge_survives_the_repetition_rescore() -> None:
    """Regression: the repetition re-score of the top candidates once rebuilt
    the composite without the time-fit term, so the nudge vanished for exactly
    the recipes that mattered. A quick recipe must keep its lift after it."""
    quick = _recipe("r_quick")
    slow = _recipe("r_slow")
    quick["cook_time_minutes"] = 20
    slow["cook_time_minutes"] = 60
    mcp = RecipeAwareMCP(
        match_ingredients={"r_quick": _match_data(0.50), "r_slow": _match_data(0.60)},
        check_repetition={"r_quick": _repetition_data(), "r_slow": _repetition_data()},
        nutrition={"r_quick": {"totals": {}}, "r_slow": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [slow, quick],
        "unified_request": _unified(max_cook_time_minutes=30, max_cook_time_is_default=True),
        "stream_messages": [],
    }
    import importlib

    # The package re-exports the function under the module's name, so import the module explicitly.
    mr = importlib.import_module("mealsight.agent.nodes.match_rank")

    original = mr.DEFAULT_TIME_FIT_WEIGHT
    mr.DEFAULT_TIME_FIT_WEIGHT = 0.25  # clearly larger than the 0.06 match gap
    try:
        result = await match_rank(state, _fake_runtime(mcp))
    finally:
        mr.DEFAULT_TIME_FIT_WEIGHT = original
    assert [r["recipe_id"] for r in result["matched_recipes"]][0] == "r_quick"
    assert result["matched_recipes"][0]["time_fit"] is True


def test_cuisine_unavailable_claim_only_fires_when_no_candidate_is_that_cuisine() -> None:
    """Regression for d2_31: an Indian request with an India-labelled candidate present
    must not be told that none of the candidates is Indian."""
    from mealsight.agent.nodes.reason import _cuisine_gap_sentence

    unified = _unified(cuisine_preference="Indian")
    assert _cuisine_gap_sentence(unified, [{"cuisine": "India"}, {"cuisine": "British"}]) is None
    assert "None of the candidates is Indian" in str(_cuisine_gap_sentence(unified, [{"cuisine": "British"}]))


async def test_peanut_free_excludes_a_violating_recipe_and_records_why() -> None:
    mcp = RecipeAwareMCP(
        match_ingredients={
            "r_pb": _match_data(0.9, matched_items=[{"name": "Peanut Butter"}]),
            "r_ok": _match_data(0.4, matched_items=[{"name": "rice"}]),
        },
        check_repetition={"r_pb": _repetition_data(), "r_ok": _repetition_data()},
        nutrition={"r_pb": {"totals": {}}, "r_ok": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("r_pb"), _recipe("r_ok")],
        "unified_request": _unified(dietary_restrictions=["peanut-free"]),
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))

    assert [r["recipe_id"] for r in result["matched_recipes"]] == ["r_ok"]
    assert result["dietary_exclusions"] == ["Recipe r_pb (peanut-free: peanut (Peanut Butter))"]
    assert any("break a dietary restriction" in m for m in result["stream_messages"])


async def test_search_sends_only_tag_backed_restrictions_as_filters() -> None:
    mcp = SequencedMCP(
        {
            ("recipe_engine", "search_recipes"): [
                ToolCallResult(success=True, data={"results": [{"id": "r"}], "total_matched": 1})
            ]
        }
    )
    state: MealSightState = {
        "unified_request": _unified(dietary_restrictions=["vegan", "peanut-free", "keto", "paleo"]),
        "context_signals": {},
        "stream_messages": [],
    }
    await search_recipes(state, _sequenced_runtime(mcp))
    assert mcp.calls[0][2]["dietary_filters"] == ["vegan"], "untagged restrictions must not be tag filters"


def test_restriction_facts_say_how_each_is_enforced_and_never_claim_a_missing_tag() -> None:
    from mealsight.agent.reasoning_facts import dietary_facts

    recipe = {"dietary_tags": ["vegan"], "matched_items": [{"name": "rice"}], "missing_items": []}
    text = " ".join(dietary_facts(recipe, ["vegan", "peanut-free", "halal", "paleo"]))
    assert "NOT tagged" not in text and "peanut-free tag" not in text
    assert "carries the vegan tag" in text
    assert "none of this recipe's 1 ingredients matched what peanut-free excludes" in text
    assert "certification cannot be verified" in text
    assert "NOT ENFORCED: paleo" in text and "may not meet it" in text
    peanut = {"matched_items": [{"name": "Peanut Butter"}]}
    assert "WARNING: breaks your peanut-free restriction" in " ".join(dietary_facts(peanut, ["peanut-free"]))


async def test_match_rank_passes_the_users_restrictions_and_avoid_list_to_the_matcher() -> None:
    """Regression: match_rank called match_ingredients without the user's constraints, so the matcher's
    dietary-rejection of substitutes never ran in production."""
    mcp = RecipeAwareMCP(
        match_ingredients={"r1": _match_data(0.5)},
        check_repetition={"r1": _repetition_data()},
        nutrition={"r1": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("r1")],
        "unified_request": _unified(
            dietary_restrictions=["dairy-free", "peanut-free"], avoid_ingredients=["mushroom"]
        ),
        "stream_messages": [],
    }
    await match_rank(state, _fake_runtime(mcp))
    sent = next(args for _s, tool, args in mcp.calls if tool == "match_ingredients")
    assert sent["dietary_restrictions"] == ["dairy-free", "peanut-free"]
    assert sent["avoid_ingredients"] == ["mushroom"]


async def test_match_rank_sends_no_constraint_keys_when_the_user_stated_none() -> None:
    mcp = RecipeAwareMCP(
        match_ingredients={"r1": _match_data(0.5)},
        check_repetition={"r1": _repetition_data()},
        nutrition={"r1": {"totals": {}}},
    )
    state: MealSightState = {
        "recipe_candidates": [_recipe("r1")],
        "unified_request": _unified(),
        "stream_messages": [],
    }
    await match_rank(state, _fake_runtime(mcp))
    sent = next(args for _s, tool, args in mcp.calls if tool == "match_ingredients")
    assert "dietary_restrictions" not in sent and "avoid_ingredients" not in sent


def _profile_state(rids: list[str], profile: dict[str, object], **unified_kwargs: object) -> MealSightState:
    return {
        "recipe_candidates": [_recipe(r) for r in rids],
        "unified_request": _unified(**unified_kwargs),
        "user_profile": profile,
        "stream_messages": [],
    }


def _two_recipe_mcp() -> RecipeAwareMCP:
    return RecipeAwareMCP(
        match_ingredients={
            "r_bacon": _match_data(0.9, matched_items=[{"name": "bacon"}]),
            "r_ok": _match_data(0.5, matched_items=[{"name": "rice"}]),
        },
        check_repetition={"r_bacon": _repetition_data(), "r_ok": _repetition_data()},
        nutrition={"r_bacon": {"totals": {}}, "r_ok": {"totals": {}}},
    )


async def test_a_saved_dislike_removes_the_recipe_when_something_else_is_cookable() -> None:
    state = _profile_state(["r_bacon", "r_ok"], {"disliked_ingredients": ["bacon"]})
    result = await match_rank(state, _fake_runtime(_two_recipe_mcp()))
    assert [r["recipe_id"] for r in result["matched_recipes"]] == ["r_ok"]
    assert result["dietary_exclusions"] == ["Recipe r_bacon (bacon)"]
    assert any("you dislike" in m for m in result["stream_messages"])


async def test_a_saved_dislike_never_leaves_nothing_cookable() -> None:
    mcp = RecipeAwareMCP(
        match_ingredients={"r_bacon": _match_data(0.9, matched_items=[{"name": "bacon"}])},
        check_repetition={"r_bacon": _repetition_data()},
        nutrition={"r_bacon": {"totals": {}}},
    )
    state = _profile_state(["r_bacon"], {"disliked_ingredients": ["bacon"]})
    result = await match_rank(state, _fake_runtime(mcp))
    assert [r["recipe_id"] for r in result["matched_recipes"]] == ["r_bacon"]
    assert result["matched_recipes"][0]["disliked_hits"] == ["bacon"]
    assert any("keeping them rather than recommending nothing" in m for m in result["stream_messages"])


async def test_a_dislike_is_also_passed_to_the_matcher_so_it_cannot_be_offered_as_a_substitute() -> None:
    mcp = _two_recipe_mcp()
    await match_rank(
        _profile_state(["r_bacon", "r_ok"], {"disliked_ingredients": ["bacon"]}), _fake_runtime(mcp)
    )
    sent = next(args for _s, tool, args in mcp.calls if tool == "match_ingredients")
    assert sent["avoid_ingredients"] == ["bacon"]


async def test_learned_cuisine_preference_applies_whatever_the_profile_key_capitalization() -> None:
    """Regression: profile keys keep their logged capitalization ('Italian'); a lower-cased lookup scored
    every cuisine neutral, so cuisine learning never affected a ranking."""
    for key in ("Italian", "italian"):
        mcp = RecordingRank(
            {"a": _match_data(0.5), "b": _match_data(0.5)},
        )
        state = _profile_state(["a", "b"], {"cuisine_preferences": {key: 0.9}})
        state["recipe_candidates"] = [_recipe("a", cuisine="Italian"), _recipe("b", cuisine="Thai")]
        result = await match_rank(state, _fake_runtime(mcp))
        scores = {r["recipe_id"]: r["cuisine_score"] for r in result["matched_recipes"]}
        assert scores == {"a": 0.9, "b": 0.5}, key


def RecordingRank(matches: dict[str, dict[str, object]]) -> RecipeAwareMCP:  # noqa: N802
    return RecipeAwareMCP(
        match_ingredients=matches,
        check_repetition={r: _repetition_data() for r in matches},
        nutrition={r: {"totals": {}} for r in matches},
    )


async def test_expiring_item_counts_when_the_recipe_line_is_less_specific_than_the_pantry_item() -> None:
    """Regression: an expiring 'chicken thigh' used by a recipe line 'chicken' earned no freshness bonus."""
    mcp = RecordingRank({"r": _match_data(0.5, matched_items=[{"name": "chicken"}])})
    state: MealSightState = {
        "recipe_candidates": [_recipe("r")],
        "unified_request": _unified(),
        "expiring_items": [{"name": "chicken thigh", "days_remaining": 1}],
        "stream_messages": [],
    }
    result = await match_rank(state, _fake_runtime(mcp))
    assert result["matched_recipes"][0]["uses_expiring_ingredient"] is True


async def test_expiring_item_flag_is_canonical_on_both_sides_and_still_distinguishes_protected_terms() -> (
    None
):
    mcp = RecordingRank({"r": _match_data(0.5, matched_items=[{"name": "tomato"}, {"name": "potato"}])})
    for expiring, expected in (("Tomatoes", True), ("sweet potato", False), ("green onion", False)):
        state: MealSightState = {
            "recipe_candidates": [_recipe("r")],
            "unified_request": _unified(),
            "expiring_items": [{"name": expiring, "days_remaining": 1}],
            "stream_messages": [],
        }
        result = await match_rank(state, _fake_runtime(mcp))
        assert result["matched_recipes"][0]["uses_expiring_ingredient"] is expected, expiring
