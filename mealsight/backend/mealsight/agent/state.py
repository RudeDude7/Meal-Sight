"""MealSightState — the LangGraph state schema for one recommendation
run.

Every field is optional (NotRequired) except stream_messages: a node
can fail, or simply have nothing to contribute for a given run (no
image was supplied, so vision_result never gets set), and leave its own
field completely unset without breaking any downstream node that
doesn't actually need it. stream_messages is the one field every node
is guaranteed to touch — see its own Annotated reducer below — so it's
the one field a caller must supply (as an empty list) when invoking the
compiled graph.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict

from mealsight.perception.models import AudioPerception, TextPerception, UnifiedMealRequest, VisionPerception


class MealSightState(TypedDict):
    # --- inputs: what the caller actually supplied for this run ---
    image_bytes: NotRequired[bytes | None]
    audio_bytes: NotRequired[bytes | None]
    text_input: NotRequired[str | None]

    # --- perception outputs: mealsight.perception's own three schemas,
    # one per modality actually provided ---
    vision_result: NotRequired[VisionPerception]
    audio_result: NotRequired[AudioPerception]
    text_result: NotRequired[TextPerception]
    unified_request: NotRequired[UnifiedMealRequest]

    # --- MCP-sourced data: plain dicts, since this is exactly the
    # shape mealsight.agent.mcp_client.MCPClientManager.call_tool
    # returns (a tool's own JSON result, already parsed) ---
    pantry_items: NotRequired[list[dict[str, Any]]]
    expiring_items: NotRequired[list[dict[str, Any]]]
    user_profile: NotRequired[dict[str, Any]]
    context_signals: NotRequired[dict[str, Any]]
    meal_history: NotRequired[list[dict[str, Any]]]
    recipe_candidates: NotRequired[list[dict[str, Any]]]
    matched_recipes: NotRequired[list[dict[str, Any]]]

    # Set by generate_output (node 9) ONLY on the cookable path: the
    # chosen recipe's own matched_items (from match_rank), cross-
    # referenced against scaled_recipe's own ingredients for a
    # quantity_display/unit — the "what's needed, and how much, for
    # what you already have" list the cook-confirmation flow
    # (mealsight.api.routers.cook) needs the frontend to be able to
    # show BEFORE a user ever confirms cooking. Node 9 itself never
    # deducts anything from the pantry (see its own module docstring);
    # this is display data only.
    matched_ingredients: NotRequired[list[dict[str, Any]]]

    # Set by search_recipes: total_matched is recipe_engine's own count
    # (which can exceed len(recipe_candidates) once max_results caps the
    # list), and search_exhausted is True only when every relaxation
    # step (see search_recipes's own docstring) still came back empty —
    # reason checks this to produce an explanation instead of inventing
    # a recommendation.
    total_matched: NotRequired[int]
    search_exhausted: NotRequired[bool]

    # --- recommendation: what the graph is actually building toward ---
    top_recommendation: NotRequired[dict[str, Any]]
    scaled_recipe: NotRequired[dict[str, Any]]
    grocery_list: NotRequired[dict[str, Any]]
    nutrition_info: NotRequired[dict[str, Any]]

    # Set by generate_output (node 9) ONLY on the cookable path, and
    # only when at least one still-missing ingredient had a real
    # find_substitutions lookup succeed: each entry is one recipe_
    # engine.models.SubstitutionResult (ingredient, reason, suggestions
    # — each with substitute/ratio/flavor_impact/notes — excluded_count).
    # Flattened here the same way matched_ingredients already is (see
    # that field's own comment above) specifically so the frontend has
    # one obvious, stable, STRUCTURED place to read ratio/flavor_impact
    # from — this data previously existed only baked into final_
    # response's own prose, with no JSON representation at all.
    substitutions: NotRequired[list[dict[str, Any]]]

    # --- output ---
    final_response: NotRequired[str]
    processing_trace: NotRequired[list[dict[str, Any]]]

    # --- cross-cutting ---
    trace_id: NotRequired[str]

    # Set by validate_input when NONE of the provided modalities were
    # both present and usable. Nodes 2-5 (phase 6.2) check this at
    # their own entry and skip their real work rather than running
    # against genuinely empty input — a per-node self-check, not a
    # change to the graph's own sequential edges (see graph.py's own
    # docstring on why real branching is deferred).
    terminal: NotRequired[bool]
    terminal_reason: NotRequired[str]

    # Every node appends its own message(s); operator.add on two lists
    # is concatenation, so this accumulates across the whole run rather
    # than each node's return value overwriting the last one's — the
    # standard LangGraph reducer idiom for an append-only field.
    stream_messages: Annotated[list[str], operator.add]

    # Populated by graph.py's own per-node timing wrapper (not by any
    # node itself) — one {"node", "duration_ms"} entry appended after
    # every node call, real or stubbed. present (node 11) reads this for
    # processing_trace's own per-node timing; same accumulate-don't-
    # overwrite reducer as stream_messages, for the same reason. Unlike
    # stream_messages, NotRequired: the wrapper supplies every entry
    # itself, so no caller needs to seed this with an initial [].
    node_timings: NotRequired[Annotated[list[dict[str, Any]], operator.add]]
