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

    assert len(mcp.calls) == 1
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

    assert call_args[0]["cuisine"] == "italian"
    assert call_args[0]["max_cook_time"] == 20
    assert call_args[0]["meal_type"] == "dinner"

    assert call_args[1]["cuisine"] is None
    assert call_args[1]["max_cook_time"] == 20
    assert call_args[1]["meal_type"] == "dinner"

    assert call_args[2]["cuisine"] is None
    assert call_args[2]["max_cook_time"] > 20
    assert call_args[2]["meal_type"] == "dinner"

    assert call_args[3]["cuisine"] is None
    assert call_args[3]["meal_type"] is None

    assert result["recipe_candidates"] == [_recipe()]
    assert result["search_exhausted"] is False
    assert any("Dropping the italian cuisine" in m for m in result["stream_messages"])
    assert any("raising the cook-time limit" in m for m in result["stream_messages"])
    assert any("dropping the dinner meal-type filter" in m for m in result["stream_messages"])


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
    assert all(args["dietary_filters"] == ["vegan", "gluten-free"] for _, _, args in mcp.calls)


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
    mcp = RecipeAwareMCP(
        match_ingredients={"r1": _match_data(0.5, matched_items=[{"name": "saffron"}])}
    )
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


def _dimension(applies: bool = True, reasoning: str = "because the data says so") -> dict[str, Any]:
    return {"applies": applies, "reasoning": reasoning}


def _decision(chosen_recipe_id: str) -> RecipeDecision:
    return RecipeDecision(
        chosen_recipe_id=chosen_recipe_id,
        ingredient_match_reasoning=_dimension(),  # type: ignore[arg-type]
        freshness_reasoning=_dimension(),  # type: ignore[arg-type]
        nutrition_reasoning=_dimension(),  # type: ignore[arg-type]
        variety_reasoning=_dimension(),  # type: ignore[arg-type]
        context_reasoning=_dimension(),  # type: ignore[arg-type]
        taste_reasoning=_dimension(),  # type: ignore[arg-type]
        overall_summary="A good pick given what's on hand.",
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
            "model_id": "mistral-medium-2505",
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "latency_ms": 500.0,
            "trace_id": "match",
        },
        {
            "model_id": "mistral-medium-2505",
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
