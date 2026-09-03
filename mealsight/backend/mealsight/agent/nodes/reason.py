"""reason — the one genuinely non-deterministic node in this graph.
Builds a compact prompt for settings.REASONING_MODEL out of everything
gathered so far and asks it to choose one recipe from matched_recipes'
own top few, justifying the choice per-dimension against the supplied
data (never general knowledge).

Recipes enter the prompt as summaries only — name, cuisine, cook time,
match/missing details, nutrition when available — never full steps or
ingredient quantities; that keeps the prompt small and matches recipe_
engine's own search_recipes contract of never returning full recipes.

The model's chosen_recipe_id is guarded: if it isn't one of the ids
actually offered, this node falls back to the top-ranked candidate and
records that the model's choice was invalid, rather than trusting an
unverifiable answer. It's also guarded on cookability: if the model
picks a candidate with can_cook=False while a cookable one is also on
offer, this node overrides to the top-ranked cookable candidate instead
— match_rank's own composite score can still rank an uncookable recipe
first (see match_rank's CRITICAL_MISSING_PENALTY docstring for the one
case it can't fully prevent: a low-score-but-no-critical-missing recipe
losing to a differently-uncookable one), and the prompt's own
instruction to prefer a cookable recipe is a request, not a guarantee.

If search_recipes came up empty (state["search_exhausted"]), no LLM
call is made at all — there's nothing to choose between — and this node
instead produces a plain explanation of what was tried. Same idea, one
level down: if every one of the top candidates has can_cook=False, no
LLM call is made either — there's nothing genuinely cookable to
recommend — and this node instead names the closest candidate's missing
ingredients as a shopping list, rather than presenting an uncookable
recipe as if it were a real suggestion.

TOKEN STREAMING, CHECKED AND NOT AVAILABLE: mealsight.providers (base.py,
mistral.py, groq.py) has no streaming support anywhere — no `stream`
parameter on any request body, no chunked/SSE response parsing, nothing
— confirmed by reading the whole provider layer before writing this
phase's own streaming work, not assumed. complete_json's own real HTTP
call to Mistral already waits for the full response before this
function ever sees any of it, so there is no token-by-token boundary
this node could tap into even in principle without first adding real
streaming support to MistralProvider itself — a materially bigger
change than "wire up the event this node already has the data for,"
and not what was asked. So this node does NOT emit stream_token events
at all (faking one token at a time out of an already-complete string
would be exactly the "faking it" this was asked not to do) — it emits
ONE "recommendation" event, via runtime.context.stream if this run has
one, once a decision (or an explanation, when nothing was cookable) is
actually ready.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime
from pydantic import BaseModel

from mealsight.agent.context import AgentContext
from mealsight.agent.state import MealSightState
from mealsight.config.settings import settings
from mealsight.providers import get_text_provider
from mealsight.providers.mistral import estimate_text_tokens
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.agent.nodes.reason")

NODE_NAME = "reason"

# How many of matched_recipes' own top candidates are shown to the
# model — the task's own "top 3-5"; only the first NUTRITION_TOP_K
# (match_rank's own constant) of these will actually carry nutrition_
# info, the rest show match details only.
CANDIDATES_IN_PROMPT = 5

SYSTEM_PROMPT = (
    "You are choosing one recipe for a home cook from a short, pre-ranked list. "
    "Base every judgment strictly on the data supplied below — never on general "
    "knowledge about the dish or cuisine. For any dimension that the supplied data "
    "doesn't speak to, set applies to false and say so plainly instead of inventing "
    "a rationale.\n"
    "\n"
    "Every candidate lists can_cook and how many ingredients it's missing. Strongly "
    "prefer a candidate with can_cook true over one with can_cook false, even if the "
    "false one ranks higher in the list — a recipe the user cannot actually make is "
    "not a good recommendation regardless of how well it otherwise fits.\n"
    "\n"
    "chosen_recipe_id must be the id of exactly one recipe from the candidates "
    "above, copied exactly — never an id that wasn't actually offered. Every one "
    "of the six *_reasoning fields is required, even when applies is false — "
    "never omit one just because it doesn't apply."
)


class DimensionReasoning(BaseModel):
    applies: bool
    reasoning: str


class RecipeDecision(BaseModel):
    chosen_recipe_id: str
    ingredient_match_reasoning: DimensionReasoning
    freshness_reasoning: DimensionReasoning
    nutrition_reasoning: DimensionReasoning
    variety_reasoning: DimensionReasoning
    context_reasoning: DimensionReasoning
    taste_reasoning: DimensionReasoning
    overall_summary: str


def _format_ingredients(unified: Any) -> str:
    lines = []
    for item in unified.available_ingredients:
        flags = []
        if not item.verified:
            flags.append("unverified")
        if item.freshness and item.freshness.lower() != "fresh":
            flags.append(f"freshness: {item.freshness}")
        suffix = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"- {item.name}{suffix}")
    return "\n".join(lines) if lines else "(none known)"


def _format_constraints(unified: Any) -> str:
    parts = [f"servings: {unified.servings}" if unified.servings else None]
    if unified.dietary_restrictions:
        parts.append(f"dietary restrictions (hard): {', '.join(unified.dietary_restrictions)}")
    if unified.max_cook_time_minutes:
        parts.append(f"max cook time: {unified.max_cook_time_minutes} minutes")
    if unified.cuisine_preference:
        parts.append(f"cuisine preference: {unified.cuisine_preference}")
    if unified.protein_preference:
        parts.append(f"protein preference: {unified.protein_preference}")
    if unified.avoid_ingredients:
        parts.append(f"avoid ingredients: {', '.join(unified.avoid_ingredients)}")
    if unified.avoid_dishes:
        parts.append(f"avoid dishes: {', '.join(unified.avoid_dishes)}")
    if unified.mood_or_preference:
        parts.append(f"mood/preference: {unified.mood_or_preference}")
    if unified.occasion:
        parts.append(f"occasion: {unified.occasion}")
    return "\n".join(f"- {p}" for p in parts if p) or "(none stated)"


def _format_expiring(expiring_items: list[dict[str, Any]]) -> str:
    if not expiring_items:
        return "(none)"
    lines = []
    for item in expiring_items:
        name = item.get("name", "?")
        remaining = item.get("days_remaining")
        suffix = f", {remaining} day(s) left" if remaining is not None else ""
        lines.append(f"- {name}{suffix}")
    return "\n".join(lines)


def _format_recipe(recipe: dict[str, Any]) -> str:
    missing = recipe.get("missing_items") or []
    lines = [
        f"id: {recipe.get('recipe_id')}",
        f"name: {recipe.get('name')}",
        f"cuisine: {recipe.get('cuisine')}, cook time: {recipe.get('cook_time_minutes')} min",
        f"ingredient match score: {recipe.get('match_score')}",
        f"can_cook: {recipe.get('can_cook')} ({len(missing)} missing ingredient(s))",
    ]
    if missing:
        lines.append(f"missing items: {', '.join(str(m) for m in missing)}")
    if recipe.get("uses_expiring_ingredient"):
        lines.append("uses an ingredient that's about to expire")
    if recipe.get("repetition_recommendation"):
        lines.append(
            f"repetition: {recipe['repetition_recommendation']} "
            f"(score {recipe.get('repetition_score')})"
        )
    nutrition = recipe.get("nutrition_info")
    if isinstance(nutrition, dict):
        coverage = nutrition.get("coverage_note") or nutrition.get("coverage_pct")
        lines.append(f"nutrition: {nutrition.get('totals', nutrition)} (coverage: {coverage})")
    return "\n".join(lines)


def _format_recent_meals(meal_history: list[dict[str, Any]]) -> str:
    if not meal_history:
        return "(none recorded)"
    names = [
        m.get("recipe_name") or m.get("name") for m in meal_history if m.get("recipe_name") or m.get("name")
    ]
    return ", ".join(str(n) for n in names) or "(none recorded)"


def _format_user_preferences(user_profile: dict[str, Any]) -> str:
    parts = []
    if user_profile.get("cuisine_preferences"):
        parts.append(f"cuisine preferences: {user_profile['cuisine_preferences']}")
    if user_profile.get("cooking_skill"):
        parts.append(f"cooking skill: {user_profile['cooking_skill']}")
    if user_profile.get("budget_sensitivity"):
        parts.append(f"budget sensitivity: {user_profile['budget_sensitivity']}")
    if user_profile.get("disliked_ingredients"):
        parts.append(f"disliked ingredients: {', '.join(user_profile['disliked_ingredients'])}")
    return "\n".join(f"- {p}" for p in parts) or "(none on file)"


def build_prompt(
    unified: Any,
    candidates: list[dict[str, Any]],
    expiring_items: list[dict[str, Any]],
    user_profile: dict[str, Any],
    meal_history: list[dict[str, Any]],
    context_signals: dict[str, Any],
) -> str:
    recipe_blocks = "\n\n".join(_format_recipe(r) for r in candidates)
    return f"""Available ingredients:
{_format_ingredients(unified)}

Constraints:
{_format_constraints(unified)}

Expiring soon:
{_format_expiring(expiring_items)}

Candidate recipes (pre-ranked, top {len(candidates)}):
{recipe_blocks}

User preferences:
{_format_user_preferences(user_profile)}

Recent meals (avoid repeating these too soon):
{_format_recent_meals(meal_history)}

Context: {context_signals or "(none)"}

Choose exactly one recipe id from the candidates above."""


def _emit_recommendation(
    stream: Any, *, recipe_id: str | None, summary: str, available: bool
) -> None:
    if stream is not None:
        stream.emit("recommendation", recipe_id=recipe_id, summary=summary, available=available)


def _fallback_decision(candidates: list[dict[str, Any]], reason_text: str) -> dict[str, Any]:
    top = candidates[0]
    return {
        "available": True,
        "recipe_id": top["recipe_id"],
        "invalid_model_choice": True,
        "invalid_choice_reason": reason_text,
        "overall_summary": f"Falling back to the top-ranked candidate: {reason_text}",
    }


def _top_cookable(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("can_cook"):
            return candidate
    return None


def _no_cookable_explanation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    closest = candidates[0]
    missing = closest.get("missing_items") or []
    missing_names = [str(m.get("name")) if isinstance(m, dict) else str(m) for m in missing]
    shopping_list = ", ".join(missing_names) if missing_names else "a few more ingredients"
    return {
        "available": False,
        "explanation": (
            "None of the top candidates are actually cookable with what's on hand right now. "
            f"The closest is {closest.get('name')} (ingredient match {closest.get('match_score')}), "
            f"missing: {shopping_list}. Buy those, or relax the cook-time/cuisine constraints to find "
            "something that better matches what's already available."
        ),
    }


def _no_candidates_explanation(state: MealSightState) -> dict[str, Any]:
    dietary = []
    unified = state.get("unified_request")
    if unified is not None:
        dietary = unified.dietary_restrictions
    kept = f" (dietary restrictions kept: {', '.join(dietary)})" if dietary else ""
    return {
        "available": False,
        "explanation": (
            "No recipes matched even after relaxing cuisine, cook time, and meal type"
            f"{kept}. Consider relaxing the cook-time limit further or adjusting dietary "
            "restrictions if flexible."
        ),
    }


async def reason(state: MealSightState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    logger.info("node_started", node=NODE_NAME)

    stream = runtime.context.stream if runtime.context is not None else None

    if state.get("terminal"):
        logger.info("node_skipped", node=NODE_NAME, reason="terminal state")
        return {"stream_messages": [f"[{NODE_NAME}] Skipped — no usable input."]}

    if state.get("search_exhausted") or not state.get("matched_recipes"):
        explanation = _no_candidates_explanation(state)
        logger.info("node_finished", node=NODE_NAME, available=False)
        _emit_recommendation(
            stream, recipe_id=None, summary=explanation["explanation"], available=False
        )
        return {
            "top_recommendation": explanation,
            "stream_messages": [f"[{NODE_NAME}] {explanation['explanation']}"],
        }

    candidates = state["matched_recipes"][:CANDIDATES_IN_PROMPT]
    unified = state.get("unified_request")
    if unified is None:
        explanation = _no_candidates_explanation(state)
        _emit_recommendation(
            stream, recipe_id=None, summary=explanation["explanation"], available=False
        )
        return {
            "top_recommendation": explanation,
            "stream_messages": [f"[{NODE_NAME}] {explanation['explanation']}"],
        }

    if not any(c.get("can_cook") for c in candidates):
        explanation = _no_cookable_explanation(candidates)
        logger.info("node_finished", node=NODE_NAME, available=False, reason="no_cookable_candidate")
        _emit_recommendation(
            stream, recipe_id=None, summary=explanation["explanation"], available=False
        )
        return {
            "top_recommendation": explanation,
            "stream_messages": [f"[{NODE_NAME}] {explanation['explanation']}"],
        }

    prompt = build_prompt(
        unified,
        candidates,
        state.get("expiring_items") or [],
        state.get("user_profile") or {},
        state.get("meal_history") or [],
        state.get("context_signals") or {},
    )

    messages: list[str] = []
    try:
        provider = get_text_provider()
        decision = await provider.complete_json(
            prompt,
            RecipeDecision,
            settings.REASONING_MODEL,
            system=SYSTEM_PROMPT,
            temperature=0.0,
        )

        candidates_by_id = {c["recipe_id"]: c for c in candidates}
        if decision.chosen_recipe_id not in candidates_by_id:
            logger.warning(
                "reason_invalid_recipe_id",
                chosen=decision.chosen_recipe_id,
                valid_ids=list(candidates_by_id),
            )
            reason_text = (
                f"model chose an id ({decision.chosen_recipe_id}) not among the candidates offered"
            )
            result = _fallback_decision(candidates, reason_text)
            messages.append(f"[{NODE_NAME}] {result['overall_summary']}")
            logger.info("node_finished", node=NODE_NAME, available=True, fallback=True)
            _emit_recommendation(
                stream, recipe_id=result["recipe_id"], summary=result["overall_summary"], available=True
            )
            return {"top_recommendation": result, "stream_messages": messages}

        chosen = candidates_by_id[decision.chosen_recipe_id]
        if not chosen.get("can_cook"):
            cookable = _top_cookable(candidates)
            if cookable is not None:
                logger.warning(
                    "reason_overriding_uncookable_model_choice",
                    model_choice=decision.chosen_recipe_id,
                    cookable_choice=cookable["recipe_id"],
                )
                result = {
                    "available": True,
                    "recipe_id": cookable["recipe_id"],
                    "invalid_model_choice": False,
                    "overrode_uncookable_choice": True,
                    "model_chosen_recipe_id": decision.chosen_recipe_id,
                    "reasoning": decision.model_dump(),
                    "overall_summary": (
                        f"The model chose {chosen.get('name')}, which isn't actually cookable with "
                        f"what's on hand — recommending {cookable.get('name')} instead, which is."
                    ),
                }
                messages.append(f"[{NODE_NAME}] {result['overall_summary']}")
                logger.info("node_finished", node=NODE_NAME, available=True, overrode_uncookable=True)
                _emit_recommendation(
                    stream, recipe_id=result["recipe_id"], summary=result["overall_summary"], available=True
                )
                return {"top_recommendation": result, "stream_messages": messages}

        result = {
            "available": True,
            "recipe_id": decision.chosen_recipe_id,
            "invalid_model_choice": False,
            "reasoning": decision.model_dump(),
            "overall_summary": decision.overall_summary,
        }
        messages.append(f"[{NODE_NAME}] Recommending: {decision.overall_summary}")
        logger.info("node_finished", node=NODE_NAME, available=True, fallback=False)
        _emit_recommendation(
            stream, recipe_id=result["recipe_id"], summary=result["overall_summary"], available=True
        )
        return {"top_recommendation": result, "stream_messages": messages}
    except Exception as exc:  # noqa: BLE001 — never raise out of a node
        logger.error("reason_unexpected_failure", exc_info=True)
        result = _fallback_decision(candidates, f"reasoning step failed unexpectedly ({exc})")
        messages.append(f"[{NODE_NAME}] {result['overall_summary']}")
        _emit_recommendation(
            stream, recipe_id=result["recipe_id"], summary=result["overall_summary"], available=True
        )
        return {"top_recommendation": result, "stream_messages": messages}


def prompt_token_count(prompt: str) -> int:
    return estimate_text_tokens(prompt)
