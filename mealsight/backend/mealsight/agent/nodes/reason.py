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

from typing import Any, Literal

from langgraph.runtime import Runtime
from pydantic import BaseModel

from mealsight.agent.context import AgentContext
from mealsight.agent.reasoning_facts import compose_reasoning, protein_met
from mealsight.agent.reasoning_facts import describe_expiry as _describe_expiry
from mealsight.agent.reasoning_facts import expiring_used_by as _expiring_used_by
from mealsight.agent.reasoning_facts import item_names as _item_names
from mealsight.agent.reasoning_facts import names_with_importance as _with_importance
from mealsight.agent.state import MealSightState
from mealsight.agent.wait_status import run_with_heartbeat
from mealsight.config.settings import settings
from mealsight.matching.cuisine import cuisines_match, lookup_cuisine_score
from mealsight.pantry.expiring import usable_pantry_names
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
    "You are choosing one recipe for a home cook from a short, pre-ranked list, and "
    "explaining the tradeoff. Every factual detail about the recipes (ingredients, "
    "expiry, nutrition, times) is shown to the user separately, taken straight from "
    "the data, so do NOT restate, summarize or recompute those facts. Your job is "
    "judgment only.\n"
    "\n"
    "1. Choose the recipe that best serves the user's request and preferences. "
    "Strongly prefer a candidate with can_cook true. Treat dietary restrictions, "
    "avoid lists and the cook-time limit as hard constraints: pick a recipe that "
    "breaks one (including a cook time that EXCEEDS the limit) only if nothing "
    "acceptable exists.\n"
    "2. Explain your choice with structured slots, not prose. chosen_because: the 1 to "
    "3 priorities that made this recipe the best choice. gave_up: the priorities this "
    "choice does worse on (empty if none). runner_up_id: the id of the closest "
    "alternative, or null. Priorities are: cookable_now, fewest_missing, time, "
    "freshness, cuisine, protein, mood, nutrition, variety, taste. The system checks "
    "each against the data and drops any that is not true, so list only what you "
    "actually weighed.\n"
    "3. variety and taste are priorities like the rest: name them in chosen_because or "
    "gave_up only if you actually weighed them; the user's meal history and preference "
    "scores are checked by the system.\n"
    "4. 'Available ingredients' and 'Pantry items at or past their estimated shelf "
    "life' describe what the user has at home, not what any recipe contains; each "
    "recipe's own contents are in its 'THIS RECIPE'S OWN INGREDIENTS' lines.\n"
    "5. chosen_recipe_id must be the exact id of one candidate (never null). You always choose "
    "one: whether anything is cookable at all is decided before you are asked. If the "
    "request is not fully met by any candidate (a cuisine, a protein, a mood), still "
    "choose the closest and say plainly in tradeoff that the request is not met. "
    "Never write that no recipe can be recommended while choosing one."
)


PriorityStatus = Literal["true", "false", "judgment", "unknown"]

PRIORITY_PHRASES: dict[str, str] = {
    "cookable_now": "being cookable with what you have",
    "fewest_missing": "needing the fewest extra ingredients",
    "time": "its cook time",
    "freshness": "using up pantry items near the end of their shelf life",
    "cuisine": "matching your cuisine preference",
    "protein": "matching your protein preference",
    "mood": "matching the mood you described",
    "nutrition": "its nutrition",
    "variety": "adding variety",
    "taste": "matching your taste preferences",
}


class RecipeDecision(BaseModel):
    """What the model decides. The factual dimensions of the reasoning shown
    to the user are NOT part of this: they are rendered from data in
    mealsight.agent.reasoning_facts."""

    # Deliberately permissive: an 8B model trips on strict enums and nulls,
    # and a validation failure costs a retry (or the whole judgment). The
    # code enforces the real constraints instead: unknown priorities are
    # ignored, a missing id falls back to the top cookable candidate.
    chosen_recipe_id: str | None = None
    chosen_because: list[str] = []
    gave_up: list[str] = []
    runner_up_id: str | None = None


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
    if unified.stated_max_cook_time_minutes:
        parts.append(f"max cook time: {unified.stated_max_cook_time_minutes} minutes")
    elif unified.max_cook_time_minutes:
        parts.append(
            f"usual cook time: about {unified.max_cook_time_minutes} minutes (a default, not a limit)"
        )
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
        expiry = _describe_expiry(item.get("days_remaining"))
        lines.append(f"- {name}: {expiry}" if expiry else f"- {name}")
    return "\n".join(lines)


def _cuisine_gap_sentence(unified: Any, candidates: list[dict[str, Any]]) -> str | None:
    """Said only when a cuisine was requested and none of the shortlisted
    candidates is that cuisine (compared through mealsight.matching.cuisine, so
    "Indian" matches the corpus label "India"). Scope is the shortlist."""
    asked = getattr(unified, "cuisine_preference", None)
    if asked and not any(cuisines_match(str(asked), str(c.get("cuisine") or "")) for c in candidates):
        return f"None of the candidates is {asked} cuisine, so that request could not be met."
    return None


def _cook_time_line(cook_time: Any, max_cook_time: int | None) -> str:
    if not isinstance(cook_time, int | float) or cook_time is None:
        return f"cook time: {cook_time} min"
    if not max_cook_time:
        return f"cook time: {cook_time} min"
    if cook_time <= max_cook_time:
        return f"cook time: {cook_time} min (within the {max_cook_time}-minute limit)"
    over = int(cook_time) - max_cook_time
    return (
        f"cook time: {cook_time} min (EXCEEDS the {max_cook_time}-minute limit by {over} min — "
        "the search had to relax the limit to find anything)"
    )


def _format_nutrition(nutrition: dict[str, Any]) -> str:
    coverage = nutrition.get("coverage_note") or nutrition.get("coverage_pct")
    fields = [
        ("calories", "calories", "kcal"),
        ("protein_g", "protein", "g"),
        ("carbs_g", "carbs", "g"),
        ("fat_g", "fat", "g"),
        ("fiber_g", "fiber", "g"),
        ("sodium_mg", "sodium", "mg"),
    ]
    if not any(key in nutrition for key, _, _ in fields):
        return f"nutrition: {nutrition.get('totals', nutrition)} (coverage: {coverage})"
    values = ", ".join(f"{label} {nutrition[key]} {unit}" for key, label, unit in fields if key in nutrition)
    servings = nutrition.get("servings")
    basis = f"per serving, at {servings} serving(s)" if servings else "per serving"
    return f"nutrition ({basis}): {values} (coverage: {coverage})"


def _format_recipe(
    recipe: dict[str, Any],
    max_cook_time: int | None = None,
    expiring_by_name: dict[str, Any] | None = None,
) -> str:
    recipe_id = recipe.get("recipe_id")
    missing = recipe.get("missing_items") or []
    in_pantry = _item_names(recipe.get("matched_items"))
    substitutes = [
        f"{i.get('original')} (you have {i.get('substitute')} instead)"
        for i in recipe.get("substitutable_items") or []
        if isinstance(i, dict)
    ]
    partials = [
        f"{i.get('name')} (you have {i.get('pantry_match')})"
        for i in recipe.get("partial_matches") or []
        if isinstance(i, dict)
    ]
    used_expiring = _expiring_used_by(recipe, expiring_by_name or {})

    lines = [
        f"===== Recipe id: {recipe_id} =====",
        f"name: {recipe.get('name')}",
        f"cuisine: {recipe.get('cuisine')}",
        _cook_time_line(recipe.get("cook_time_minutes"), max_cook_time),
        f"ingredient match score: {recipe.get('match_score')}",
        f"can_cook: {recipe.get('can_cook')} ({len(missing)} missing ingredient(s))",
        "THIS RECIPE'S OWN INGREDIENTS (the only ingredients this recipe contains):",
        f"  - the user has: {', '.join(in_pantry) if in_pantry else '(none)'}",
    ]
    if substitutes:
        lines.append(f"  - the user has a substitute for: {', '.join(substitutes)}")
    if partials:
        lines.append(f"  - the user has only a less specific form of: {', '.join(partials)}")
    lines.append(f"  - the user does NOT have (missing): {', '.join(_with_importance(missing)) or '(none)'}")
    lines.append(
        "expired or expiring pantry items this recipe uses: "
        + (", ".join(used_expiring) if used_expiring else "none")
    )
    if recipe.get("repetition_recommendation"):
        lines.append(
            f"repetition: {recipe['repetition_recommendation']} (score {recipe.get('repetition_score')})"
        )
    nutrition = recipe.get("nutrition_info")
    if isinstance(nutrition, dict):
        lines.append(_format_nutrition(nutrition))
    lines.append(f"===== end of recipe {recipe_id} =====")
    return "\n".join(lines)


def _format_context_signals(context_signals: dict[str, Any]) -> str:
    """Renders get_context_signals' own output (meal_type,
    complexity_suggestion, context_notes, and — when available —
    temperature_f/conditions/mood_suggestion) as plain lines, instead of
    a raw dict repr. The weather line is included ONLY when weather data
    is actually present; when it's absent, this function emits nothing
    for it at all, rather than a placeholder like "weather: unknown" —
    an explicit absence in the prompt text is what lets SYSTEM_PROMPT's
    own existing "mark not applicable, don't invent a rationale" rule
    apply to weather exactly the way it already applies to every other
    dimension the supplied data doesn't speak to, with no weather-
    specific special case needed here.

    mood_suggestion is stated as a SUGGESTION, matching this whole
    project's own repeated framing (settings, prompt copy, docs) that
    it must never act as a filter — worded here as "a possible cue", not
    an instruction.
    """
    if not context_signals:
        return "(none)"

    lines = []
    meal_type = context_signals.get("meal_type")
    if meal_type:
        lines.append(f"- meal_type: {meal_type}")
    complexity_suggestion = context_signals.get("complexity_suggestion")
    if complexity_suggestion:
        lines.append(f"- complexity: {complexity_suggestion}")
    for note in context_signals.get("context_notes") or []:
        lines.append(f"- {note}")

    temperature_f = context_signals.get("temperature_f")
    conditions = context_signals.get("conditions")
    mood_suggestion = context_signals.get("mood_suggestion")
    if temperature_f is not None and conditions and mood_suggestion:
        lines.append(
            f"- current weather: {temperature_f:.0f}F, {conditions} "
            f"(a possible cue toward {mood_suggestion} food — a suggestion only, "
            "never a reason to exclude what the user actually asked for)"
        )

    return "\n".join(lines) if lines else "(none)"


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
    expiring_by_name = {
        str(i["name"]).lower(): i.get("days_remaining") for i in expiring_items if i.get("name")
    }
    max_cook_time = getattr(unified, "stated_max_cook_time_minutes", None)
    recipe_blocks = "\n\n".join(_format_recipe(r, max_cook_time, expiring_by_name) for r in candidates)
    return f"""THE USER'S PANTRY (what the user has at home; this says nothing about what any recipe contains)

Available ingredients:
{_format_ingredients(unified)}

Pantry items at or past their estimated shelf life:
{_format_expiring(expiring_items)}

THE USER'S REQUEST

Constraints:
{_format_constraints(unified)}

CANDIDATE RECIPES (pre-ranked, top {len(candidates)}; each block describes only that one recipe)

{recipe_blocks}

User preferences:
{_format_user_preferences(user_profile)}

Recent meals (avoid repeating these too soon):
{_format_recent_meals(meal_history)}

Context:
{_format_context_signals(context_signals)}

Choose one recipe id from the candidates above (or null if none is acceptable) and explain the tradeoff."""


_REASON_IDLE_TEXTS = (
    "Asking the model to weigh the candidates against your pantry, history and context.",
    "The model is still choosing between the candidates.",
    "Almost there: the model is writing up why it picked this recipe.",
)


def _emit_progress(stream: Any, text: str) -> None:
    """A progress line for the still-running reason node, sent as a node_start carrying `detail` (no new
    message type): the UI replaces the step's line in place instead of stacking text."""
    if stream is not None:
        stream.emit("node_start", node=NODE_NAME, detail=text)


def _emit_recommendation(stream: Any, *, recipe_id: str | None, summary: str, available: bool) -> None:
    if stream is not None:
        stream.emit("recommendation", recipe_id=recipe_id, summary=summary, available=available)


def _build_reasoning(recipe: dict[str, Any], state: MealSightState, summary: str) -> dict[str, Any]:
    """The six dimensions for the recipe actually being returned, all
    rendered from data. The model's judgment reaches the user only through
    the summary sentence (see _render_tradeoff). Built for the returned
    recipe every time, so the reasoning can never describe a different
    recipe than the one returned."""
    return {
        "chosen_recipe_id": recipe["recipe_id"],
        **compose_reasoning(
            recipe,
            unified=state.get("unified_request"),
            expiring_items=state.get("expiring_items") or [],
            waste_candidates=state.get("waste_candidates") or [],
            user_profile=state.get("user_profile") or {},
            meal_history=state.get("meal_history") or [],
            context_signals=state.get("context_signals") or {},
            candidates=state.get("matched_recipes") or [],
            pantry_names=usable_pantry_names(state.get("pantry_items") or []),
        ),
        "overall_summary": summary,
    }


def _priority_status(
    priority: str, chosen: dict[str, Any], candidates: list[dict[str, Any]], state: MealSightState
) -> PriorityStatus:
    """What the data says about the chosen recipe on this priority:
    "true" / "false" when it can be settled, "judgment" for the two that are
    genuinely a matter of taste (mood, nutrition) once their data exists, and
    "unknown" when the data to settle it is absent. Only "true" may be
    given as a reason and only "false" as a compromise; a judgment may be
    either; unknown is never stated."""
    unified = state.get("unified_request")
    profile = state.get("user_profile") or {}

    def settled(value: bool | None) -> PriorityStatus:
        return "unknown" if value is None else ("true" if value else "false")

    if priority not in PRIORITY_PHRASES:
        return "unknown"
    if priority == "cookable_now":
        return settled(bool(chosen.get("can_cook")))
    if priority == "fewest_missing":
        missing = len(chosen.get("missing_items") or [])
        return settled(missing <= min(len(c.get("missing_items") or []) for c in candidates))
    if priority == "time":
        cook = chosen.get("cook_time_minutes")
        limit = getattr(unified, "stated_max_cook_time_minutes", None)
        if not isinstance(cook, int | float):
            return "unknown"
        if limit:
            return settled(bool(cook <= limit))
        times = [
            c["cook_time_minutes"] for c in candidates if isinstance(c.get("cook_time_minutes"), int | float)
        ]
        return settled(bool(cook <= min(times)))
    if priority == "freshness":
        expiring = {
            str(i["name"]).lower(): i.get("days_remaining")
            for i in state.get("expiring_items") or []
            if i.get("name")
        }
        return settled(bool(_expiring_used_by(chosen, expiring)) if expiring else None)
    if priority == "cuisine":
        asked = getattr(unified, "cuisine_preference", None)
        if not asked:
            return "unknown"
        return settled(cuisines_match(str(asked), str(chosen.get("cuisine") or "")))
    if priority == "protein":
        asked = getattr(unified, "protein_preference", None)
        return settled(protein_met(str(asked), chosen)) if asked else "unknown"
    if priority == "mood":
        return "judgment" if getattr(unified, "mood_or_preference", None) else "unknown"
    if priority == "nutrition":
        return "judgment" if isinstance(chosen.get("nutrition_info"), dict) else "unknown"
    if priority == "variety":
        recommendation = chosen.get("repetition_recommendation")
        return settled(recommendation == "acceptable") if recommendation else "unknown"
    if priority == "taste":
        scores = profile.get("cuisine_preferences") or {}
        score = lookup_cuisine_score(scores, str(chosen.get("cuisine") or "") or None, -1.0)
        if score < 0:
            return "unknown"
        return settled(score >= 0.5)
    return "unknown"


def _join(phrases: list[str]) -> str:
    return phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]


def _render_tradeoff(
    decision: RecipeDecision,
    chosen: dict[str, Any],
    candidates: list[dict[str, Any]],
    state: MealSightState,
) -> str:
    """The sentence shown as the overall summary, built from the model's
    structured judgment. Every priority the data can settle is checked and
    dropped if untrue, so no claim here depends on the model being right
    about the facts; the model only decides what it weighed."""
    kept: list[str] = []
    for priority in dict.fromkeys(decision.chosen_because):
        status = _priority_status(priority, chosen, candidates, state)
        if status in ("true", "judgment"):
            kept.append(PRIORITY_PHRASES[priority])
        else:
            logger.warning(
                "reason_priority_not_supported",
                priority=priority,
                status=status,
                recipe=chosen.get("name"),
            )
    gave_up = [
        PRIORITY_PHRASES[p]
        for p in dict.fromkeys(decision.gave_up)
        if p not in decision.chosen_because
        and _priority_status(p, chosen, candidates, state) in ("false", "judgment")
    ]

    name = chosen.get("name")
    sentences = [f"{name} was chosen for {_join(kept)}." if kept else f"{name} is the best available match."]
    if gave_up:
        sentences.append(f"The compromise is {_join(gave_up)}.")
    gap = _cuisine_gap_sentence(state.get("unified_request"), candidates)
    if gap:
        sentences.append(gap)
    runner_up = next(
        (c for c in candidates if c.get("recipe_id") == decision.runner_up_id and c is not chosen), None
    )
    if runner_up is not None:
        sentences.append(f"The closest alternative was {runner_up.get('name')}.")
    return " ".join(sentences)


def _fallback_decision(
    candidates: list[dict[str, Any]], reason_text: str, state: MealSightState
) -> dict[str, Any]:
    top = candidates[0]
    summary = f"Falling back to the top-ranked candidate: {reason_text}"
    return {
        "available": True,
        "recipe_id": top["recipe_id"],
        "invalid_model_choice": True,
        "invalid_choice_reason": reason_text,
        "reasoning": _build_reasoning(top, state, summary),
        "overall_summary": summary,
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
    excluded = state.get("dietary_exclusions") or []
    if excluded and not state.get("search_exhausted"):
        # The search found recipes; every one was ruled out by a dietary restriction or avoid list.
        unenforced = list(getattr(unified, "unenforced_restrictions", []) or [])
        note = f" Not enforced (cannot be verified): {', '.join(unenforced)}." if unenforced else ""
        return {
            "available": False,
            "explanation": (
                f"Every recipe the search found was ruled out by your dietary restrictions or avoid "
                f"list{kept}: {'; '.join(excluded[:3])}.{note}"
            ),
        }
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
        _emit_recommendation(stream, recipe_id=None, summary=explanation["explanation"], available=False)
        return {
            "top_recommendation": explanation,
            "stream_messages": [f"[{NODE_NAME}] {explanation['explanation']}"],
        }

    candidates = state["matched_recipes"][:CANDIDATES_IN_PROMPT]
    unified = state.get("unified_request")
    if unified is None:
        explanation = _no_candidates_explanation(state)
        _emit_recommendation(stream, recipe_id=None, summary=explanation["explanation"], available=False)
        return {
            "top_recommendation": explanation,
            "stream_messages": [f"[{NODE_NAME}] {explanation['explanation']}"],
        }

    if not any(c.get("can_cook") for c in candidates):
        explanation = _no_cookable_explanation(candidates)
        logger.info("node_finished", node=NODE_NAME, available=False, reason="no_cookable_candidate")
        _emit_recommendation(stream, recipe_id=None, summary=explanation["explanation"], available=False)
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
    result: dict[str, Any]
    try:
        provider = get_text_provider()
        decision = await run_with_heartbeat(
            provider.complete_json(
                prompt,
                RecipeDecision,
                settings.REASONING_MODEL,
                system=SYSTEM_PROMPT,
                temperature=0.0,
            ),
            model_id=settings.REASONING_MODEL,
            emit=lambda text: _emit_progress(stream, text),
            idle_texts=_REASON_IDLE_TEXTS,
        )

        candidates_by_id = {c["recipe_id"]: c for c in candidates}
        if decision.chosen_recipe_id is None:
            # The model tried to decline. Whether anything is cookable at all
            # is decided before it is asked, so a null id is not a refusal:
            # take the top cookable candidate and say it is the closest.
            fallback_pick = _top_cookable(candidates) or candidates[0]
            logger.warning("reason_model_returned_no_id", using=fallback_pick["recipe_id"])
            decision = decision.model_copy(update={"chosen_recipe_id": fallback_pick["recipe_id"]})
        if decision.chosen_recipe_id not in candidates_by_id:
            logger.warning(
                "reason_invalid_recipe_id",
                chosen=decision.chosen_recipe_id,
                valid_ids=list(candidates_by_id),
            )
            reason_text = f"model chose an id ({decision.chosen_recipe_id}) not among the candidates offered"
            result = _fallback_decision(candidates, reason_text, state)
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
                summary = (
                    f"The model chose {chosen.get('name')}, which isn't actually cookable with "
                    f"what's on hand — recommending {cookable.get('name')} instead, which is."
                )
                result = {
                    "available": True,
                    "recipe_id": cookable["recipe_id"],
                    "invalid_model_choice": False,
                    "overrode_uncookable_choice": True,
                    "model_chosen_recipe_id": decision.chosen_recipe_id,
                    "reasoning": _build_reasoning(cookable, state, summary),
                    "overall_summary": summary,
                }
                messages.append(f"[{NODE_NAME}] {result['overall_summary']}")
                logger.info("node_finished", node=NODE_NAME, available=True, overrode_uncookable=True)
                _emit_recommendation(
                    stream, recipe_id=result["recipe_id"], summary=result["overall_summary"], available=True
                )
                return {"top_recommendation": result, "stream_messages": messages}

        tradeoff = _render_tradeoff(decision, chosen, candidates, state)
        result = {
            "available": True,
            "recipe_id": decision.chosen_recipe_id,
            "invalid_model_choice": False,
            "reasoning": _build_reasoning(chosen, state, tradeoff),
            "overall_summary": tradeoff,
        }
        messages.append(f"[{NODE_NAME}] Recommending: {tradeoff}")
        logger.info("node_finished", node=NODE_NAME, available=True, fallback=False)
        _emit_recommendation(
            stream, recipe_id=result["recipe_id"], summary=result["overall_summary"], available=True
        )
        return {"top_recommendation": result, "stream_messages": messages}
    except Exception as exc:  # noqa: BLE001 — never raise out of a node
        logger.error("reason_unexpected_failure", exc_info=True)
        result = _fallback_decision(candidates, f"reasoning step failed unexpectedly ({exc})", state)
        messages.append(f"[{NODE_NAME}] {result['overall_summary']}")
        _emit_recommendation(
            stream, recipe_id=result["recipe_id"], summary=result["overall_summary"], available=True
        )
        return {"top_recommendation": result, "stream_messages": messages}


def prompt_token_count(prompt: str) -> int:
    return estimate_text_tokens(prompt)
