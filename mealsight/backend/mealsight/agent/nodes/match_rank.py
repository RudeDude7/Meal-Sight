"""match_rank — narrows recipe_candidates down to a short, LLM-ready
list for reason (node 8).

Three MCP calls per candidate/tier, all fast local Python inside
recipe_engine/user_intelligence (no LLM, no rate limit to respect here —
that constraint only applies to reason's own call into REASONING_MODEL):

  1. match_ingredients, for the top TOP_N_CANDIDATES_TO_MATCH candidates
     (by recipe_engine's own search order) against the ACCUMULATED
     pantry — state["pantry_items"], populated by update_pantry (node 4)
     via get_pantry — not just what THIS run's photo happened to show.
     An item only ever mentioned in speech or text (never seen, so not
     in the persisted pantry either) is still included, since the user
     said it's there, but tracked separately: see
     unverified_ingredient_matches on each scored entry below.
  2. check_repetition, for only the top CHECK_REPETITION_TOP_K of those
     by preliminary score — its own recommendation ("too_repetitive"
     etc.) is a signal to weigh here, per that tool's own docstring,
     never a hard veto.
  3. calculate_nutrition, for only the final top NUTRITION_TOP_K — kept
     small since this all enters an LLM context window next.

Ranking is a deterministic, Python-computed composite score — never an
LLM judgment. It exists to narrow the field; reason (node 8) makes the
final choice among the top few using its own judgment plus data this
node can't weigh numerically (context signals, mood, taste).

Weights (see the module-level constants below) are additive except for
the repetition penalty and the critical-missing penalty, which are
subtracted. ingredient match score is the dominant term; freshness,
cuisine preference, and repetition are secondary signals layered on
top — but see CRITICAL_MISSING_PENALTY: those secondary signals are
never allowed to lift a recipe that's missing a critical ingredient
above one that isn't.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from mealsight.agent.context import AgentContext
from mealsight.agent.state import MealSightState
from mealsight.matching.normalize import normalize_ingredient
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.match_rank")

NODE_NAME = "match_rank"

# How many search_recipes candidates get match_ingredients called
# against them at all. Configurable — raise it to widen the field this
# node considers, at the cost of more (still-fast, local) MCP calls.
TOP_N_CANDIDATES_TO_MATCH = 10

# Of those, how many (by preliminary score) get check_repetition called
# — kept smaller than TOP_N_CANDIDATES_TO_MATCH since repetition lookups
# hit user_intelligence's own history store per call.
CHECK_REPETITION_TOP_K = 5

# Of the final ranked list, how many get calculate_nutrition called —
# the task's own instruction: top 3 only, to keep the eventual LLM
# payload small.
NUTRITION_TOP_K = 3

# --- composite score weights, sum to 1.0 (before any penalty) ---
# Dominant term: can we actually make this with what's on hand.
INGREDIENT_MATCH_WEIGHT = 0.6
# Flat bonus (not scaled by anything) when the recipe uses an
# ingredient that's about to expire — using it up is worth rewarding
# regardless of how strong the overall match is.
FRESHNESS_BONUS_WEIGHT = 0.15
# Softer, learned signal from the user's own cuisine history.
CUISINE_PREFERENCE_WEIGHT = 0.15
# Subtracted: how repetitive check_repetition says this recipe would be.
REPETITION_PENALTY_WEIGHT = 0.10

# Neutral score for a cuisine the user has no recorded preference for —
# absence of data isn't evidence of dislike.
NEUTRAL_CUISINE_SCORE = 0.5

# A recipe missing a CRITICAL ingredient has match_score clamped toward
# 0 by mealsight.matching's own critical_missing_penalty, but its
# matched_items (the non-critical ingredients it DOES have) survive that
# clamp — so it could still pick up the freshness bonus and a neutral-
# or-better cuisine score. Two recipes can both be can_cook=False (one
# from a missing critical ingredient, one just from a low score) and
# still need to be ordered relative to each other, so the gate has to be
# critical_missing specifically, not the coarser can_cook flag: e.g.
# Coq au vin (critical_missing=['bacon'], match_score 0.0, matches the
# run's expiring chicken thigh) previously composited to 0.225 — ahead
# of Baingan Bharta (no critical ingredient missing, match_score 0.1111,
# no bonuses) at 0.14166 — even though Baingan Bharta is strictly more
# cookable. CRITICAL_MISSING_PENALTY (1.0, bigger than the maximum
# possible sum of every other positive term: 0.6 + 0.15 + 0.15 = 0.9) is
# subtracted whenever critical_missing is non-empty, so that can never
# happen again: a recipe missing a critical ingredient always scores
# lower than one that isn't, regardless of freshness/cuisine/repetition.
CRITICAL_MISSING_PENALTY = 1.0


def _composite_score(
    match_score: float,
    uses_expiring_ingredient: bool,
    cuisine_score: float,
    repetition_score: float,
    has_critical_missing: bool,
) -> float:
    score = INGREDIENT_MATCH_WEIGHT * match_score
    if uses_expiring_ingredient:
        score += FRESHNESS_BONUS_WEIGHT
    score += CUISINE_PREFERENCE_WEIGHT * cuisine_score
    score -= REPETITION_PENALTY_WEIGHT * repetition_score
    if has_critical_missing:
        score -= CRITICAL_MISSING_PENALTY
    return score


def _pantry_and_unverified_names(state: MealSightState) -> tuple[list[str], set[str]]:
    """The accumulated pantry (state["pantry_items"], from update_pantry's
    own get_pantry read-back) is the primary ingredient source. Anything
    the user only ever mentioned in speech/text — never actually seen,
    so never written to the pantry — is still appended as usable, since
    the user said it's there; pantry_normalized is returned alongside so
    callers can tell which matched ingredient names came ONLY from that
    unverified set (see unverified_ingredient_matches below)."""
    pantry_entries = state.get("pantry_items") or []
    pantry_names = [str(item["name"]) for item in pantry_entries if item.get("name")]
    pantry_normalized = {normalize_ingredient(name) for name in pantry_names}

    unified = state.get("unified_request")
    unverified_names = (
        [item.name for item in unified.available_ingredients if not item.verified]
        if unified is not None
        else []
    )

    available_names = list(pantry_names)
    for name in unverified_names:
        if normalize_ingredient(name) not in pantry_normalized:
            available_names.append(name)

    return available_names, pantry_normalized


def _unverified_only_matches(matched_items: list[Any], pantry_normalized: set[str]) -> list[str]:
    result = []
    for item in matched_items:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and normalize_ingredient(name) not in pantry_normalized:
            result.append(name)
    return result


def _cuisine_score(recipe_cuisine: str | None, cuisine_preferences: dict[str, Any]) -> float:
    if not recipe_cuisine:
        return NEUTRAL_CUISINE_SCORE
    raw = cuisine_preferences.get(recipe_cuisine.lower())
    if not isinstance(raw, (int, float)):
        return NEUTRAL_CUISINE_SCORE
    return float(raw)


def _uses_expiring_ingredient(matched_items: list[Any], expiring_names: set[str]) -> bool:
    for item in matched_items:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name.lower() in expiring_names:
            return True
    return False


async def _match_ingredients(
    runtime: Runtime[AgentContext], recipe_id: str, ingredient_names: list[str]
) -> dict[str, Any] | None:
    result = await runtime.context.mcp.call_tool(
        "recipe_engine",
        "match_ingredients",
        {"recipe_id": recipe_id, "available_ingredients": ingredient_names},
    )
    if result.success and isinstance(result.data, dict):
        return result.data
    logger.warning("match_ingredients_call_failed", recipe_id=recipe_id, error=result.error)
    return None


async def _check_repetition(runtime: Runtime[AgentContext], recipe_id: str) -> dict[str, Any] | None:
    result = await runtime.context.mcp.call_tool(
        "user_intelligence", "check_repetition", {"recipe_id": recipe_id}
    )
    if result.success and isinstance(result.data, dict):
        return result.data
    logger.warning("check_repetition_call_failed", recipe_id=recipe_id, error=result.error)
    return None


async def _calculate_nutrition(
    runtime: Runtime[AgentContext], recipe_id: str, servings: int | None
) -> dict[str, Any] | None:
    arguments: dict[str, Any] = {"recipe_id": recipe_id}
    if servings is not None:
        arguments["servings"] = servings
    result = await runtime.context.mcp.call_tool("recipe_engine", "calculate_nutrition", arguments)
    if result.success and isinstance(result.data, dict):
        return result.data
    logger.warning("calculate_nutrition_call_failed", recipe_id=recipe_id, error=result.error)
    return None


async def match_rank(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input."]}

    candidates = state.get("recipe_candidates") or []
    if not candidates:
        logger.info("node_skipped", node=NODE_NAME, reason="no recipe candidates")
        return {"matched_recipes": [], "stream_messages": [f"[{NODE_NAME}] No recipe candidates to rank."]}

    unified = state.get("unified_request")
    ingredient_names, pantry_normalized = _pantry_and_unverified_names(state)
    expiring_names = {
        item.get("name", "").lower() for item in (state.get("expiring_items") or []) if item.get("name")
    }
    user_profile = state.get("user_profile") or {}
    cuisine_preferences = user_profile.get("cuisine_preferences") or {}
    servings = getattr(unified, "servings", None) if unified is not None else None

    messages: list[str] = []

    try:
        tier = candidates[:TOP_N_CANDIDATES_TO_MATCH]
        scored: list[dict[str, Any]] = []
        for recipe in tier:
            recipe_id = recipe.get("recipe_id") or recipe.get("id")
            if not recipe_id:
                continue
            match_data = await _match_ingredients(runtime, recipe_id, ingredient_names)
            if match_data is None:
                continue
            match_score = float(match_data.get("match_score", 0.0))
            matched_items = match_data.get("matched_items") or []
            critical_missing = match_data.get("critical_missing") or []
            uses_expiring = _uses_expiring_ingredient(matched_items, expiring_names)
            cuisine_score = _cuisine_score(recipe.get("cuisine"), cuisine_preferences)
            scored.append(
                {
                    **recipe,
                    "recipe_id": recipe_id,
                    "match_score": match_score,
                    "can_cook": match_data.get("can_cook"),
                    "matched_items": matched_items,
                    "substitutable_items": match_data.get("substitutable_items"),
                    "partial_matches": match_data.get("partial_matches"),
                    "missing_items": match_data.get("missing_items"),
                    "critical_missing": critical_missing,
                    "match_summary": match_data.get("summary"),
                    "uses_expiring_ingredient": uses_expiring,
                    "cuisine_score": cuisine_score,
                    "repetition_score": 0.0,
                    "repetition_recommendation": None,
                    "unverified_ingredient_matches": _unverified_only_matches(
                        matched_items, pantry_normalized
                    ),
                    "composite_score": _composite_score(
                        match_score, uses_expiring, cuisine_score, 0.0, bool(critical_missing)
                    ),
                }
            )
        messages.append(f"[{NODE_NAME}] Matched ingredients against {len(scored)} candidate recipe(s).")

        scored.sort(key=lambda r: r["composite_score"], reverse=True)

        repetition_tier = scored[:CHECK_REPETITION_TOP_K]
        for entry in repetition_tier:
            rep_data = await _check_repetition(runtime, entry["recipe_id"])
            if rep_data is None:
                continue
            repetition_score = float(rep_data.get("repetition_score", 0.0))
            entry["repetition_score"] = repetition_score
            entry["repetition_recommendation"] = rep_data.get("recommendation")
            entry["composite_score"] = _composite_score(
                entry["match_score"],
                entry["uses_expiring_ingredient"],
                entry["cuisine_score"],
                repetition_score,
                bool(entry["critical_missing"]),
            )
        if repetition_tier:
            messages.append(f"[{NODE_NAME}] Checked recent-repetition for the top {len(repetition_tier)}.")

        scored.sort(key=lambda r: r["composite_score"], reverse=True)

        nutrition_tier = scored[:NUTRITION_TOP_K]
        for entry in nutrition_tier:
            nutrition_data = await _calculate_nutrition(runtime, entry["recipe_id"], servings)
            if nutrition_data is not None:
                entry["nutrition_info"] = nutrition_data
        if nutrition_tier:
            messages.append(f"[{NODE_NAME}] Calculated nutrition for the top {len(nutrition_tier)}.")

        logger.info("node_finished", node=NODE_NAME, ranked=len(scored))
        return {"matched_recipes": scored, "stream_messages": messages}
    except Exception:
        logger.error("match_rank_unexpected_failure", exc_info=True)
        messages.append(f"[{NODE_NAME}] Ranking failed unexpectedly.")
        return {"matched_recipes": [], "stream_messages": messages}
