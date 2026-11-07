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

Each candidate also emits a "recipe_match" progress event the moment
its own match_ingredients call resolves, via runtime.context.stream if
this run has one — this loop is otherwise the second-longest visible
wait in a real run (several sequential, fast local MCP calls), and a
per-candidate event is what lets a client show matching progress
recipe by recipe instead of one silent wait followed by a single
"done."

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
from mealsight.agent.reasoning_facts import _recipe_ingredient_names
from mealsight.agent.state import MealSightState
from mealsight.matching.avoid import dish_hits as avoid_dish_hits
from mealsight.matching.avoid import ingredient_hits as avoid_ingredient_hits
from mealsight.matching.cuisine import lookup_cuisine_score
from mealsight.matching.diet import split_restrictions, violated_ingredient_restrictions
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.protein import is_general_protein_request, names_include_protein
from mealsight.matching.specificity import compare_specificity
from mealsight.pantry.expiring import usable_pantry_names
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

# Flat lift for a recipe that contains the protein the user asked for AND
# can actually be cooked now. Set equal to the cuisine weight: a stated
# preference about what to eat deserves the same pull as learned taste. It
# is worth a 0.25 gap in ingredient match (0.15 / 0.6), so a cookable recipe
# with the asked-for protein beats a cookable one without it unless the
# latter is clearly better-stocked. It is deliberately NOT a filter, and it
# is gated on can_cook: an uncookable recipe gets no lift, so an uncookable
# seafood dish can never outrank a cookable chicken one.
PROTEIN_PREFERENCE_WEIGHT = 0.15

# A profile-default cook time (the user stated none) only nudges: a cookable
# recipe within it gets this lift. It is never a filter, so a request like "a
# vegan recipe" can still reach the 60-minute vegan dish that is the only one
# the pantry supports. A time the user STATED is a hard filter in
# search_recipes and does not come through here.
#
# 0.15 chosen by measurement (14 no-time requests, profile preference 30 min;
# eval notes in backend/eval/README.md): the top-ranked recipe was within the
# preference 0/14 at 0.0, 1/14 at 0.05, 13/14 at 0.15 and 13/14 at 0.25. 0.15 is
# the smallest weight that reaches it; 0.25 adds nothing. The most ingredient
# match given up was 0.11 (mean 0.067), and every top pick stayed cookable.
# It equals the cuisine and protein weights on purpose.
DEFAULT_TIME_FIT_WEIGHT = 0.15


def _composite_score(
    match_score: float,
    uses_expiring_ingredient: bool,
    cuisine_score: float,
    repetition_score: float,
    has_critical_missing: bool,
    protein_lift: bool = False,
    time_fit: bool = False,
) -> float:
    score = INGREDIENT_MATCH_WEIGHT * match_score
    if time_fit:
        score += DEFAULT_TIME_FIT_WEIGHT
    if protein_lift:
        score += PROTEIN_PREFERENCE_WEIGHT
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
    # Items far past their shelf life are waste, not ingredients (same
    # cutoff as the freshness bonus): a recipe needing one reports it as
    # missing, so can_cook and the score stay honest. They still count as
    # "in the pantry" below, so a spoken mention of one is not re-added as
    # an unverified ingredient behind the cutoff's back.
    pantry_names = usable_pantry_names(pantry_entries)
    pantry_normalized = {
        normalize_ingredient(str(item["name"])) for item in pantry_entries if item.get("name")
    }

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
    # Matched by cuisine family, not by exact key: profile scores keep the capitalization the meal was
    # logged with ("Italian"), and a lower-cased lookup silently scored every cuisine neutral.
    return lookup_cuisine_score(cuisine_preferences, recipe_cuisine, NEUTRAL_CUISINE_SCORE)


def _uses_expiring_ingredient(matched_items: list[Any], expiring_names: set[str]) -> bool:
    """Whether a matched recipe line is satisfied by an expiring pantry item. Both sides are compared in
    canonical form, and a pantry item that is a more specific cut or variety of the line counts (an expiring
    "chicken thigh" is what a recipe line "chicken" is cooked with). The matcher reports the RECIPE's
    canonical name, so comparing it with the raw pantry name missed every specificity match."""
    expiring = {normalize_ingredient(n) for n in expiring_names if n}
    for item in matched_items:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str):
            continue
        line = normalize_ingredient(name)
        for pantry in expiring:
            if line == pantry or compare_specificity(line, pantry) == "full":
                return True
    return False


async def _match_ingredients(
    runtime: Runtime[AgentContext],
    recipe_id: str,
    ingredient_names: list[str],
    dietary_restrictions: list[str] | None = None,
    avoid_ingredients: list[str] | None = None,
) -> dict[str, Any] | None:
    """Every caller that knows the user's constraints must pass them: the matcher refuses a
    substitute that breaks a restriction or an avoid list, but only if it is told what they are."""
    arguments: dict[str, Any] = {"recipe_id": recipe_id, "available_ingredients": ingredient_names}
    if dietary_restrictions:
        arguments["dietary_restrictions"] = dietary_restrictions
    if avoid_ingredients:
        arguments["avoid_ingredients"] = avoid_ingredients
    result = await runtime.context.mcp.call_tool("recipe_engine", "match_ingredients", arguments)
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
    # Saved dislikes are enforced in code, not by hoping the model reads a prompt line (see below).
    disliked_terms = [str(d) for d in (user_profile.get("disliked_ingredients") or []) if d]
    servings = getattr(unified, "servings", None) if unified is not None else None
    stated_protein = getattr(unified, "protein_preference", None) if unified is not None else None
    # "high-protein" is a nutrition ask, settled later from nutrition figures
    # that only exist for the top few; only a specific protein lifts here.
    protein_pref = None
    if stated_protein and not is_general_protein_request(str(stated_protein)):
        protein_pref = str(stated_protein)
    default_time = (
        getattr(unified, "max_cook_time_minutes", None)
        if unified is not None and getattr(unified, "max_cook_time_is_default", False)
        else None
    )
    avoid_terms = [str(a) for a in (getattr(unified, "avoid_ingredients", None) or []) if a]
    avoid_dishes = [str(d) for d in (getattr(unified, "avoid_dishes", None) or []) if d]
    split = split_restrictions(list(getattr(unified, "dietary_restrictions", None) or []))
    has_dietary_rules = bool(split.ingredient)
    stream = runtime.context.stream if runtime.context is not None else None

    messages: list[str] = []

    try:
        # A protein preference can only lift candidates that get scored, so
        # when one is stated every candidate search returned is matched
        # (local MCP calls) rather than only the first TOP_N.
        # Likewise when an avoid list is stated: the exclusion below has to see
        # every candidate, or a clean recipe past the cutoff is never reached.
        stated_filters = bool(
            protein_pref or avoid_terms or avoid_dishes or has_dietary_rules or disliked_terms
        )
        tier = candidates if stated_filters else candidates[:TOP_N_CANDIDATES_TO_MATCH]
        scored: list[dict[str, Any]] = []
        excluded_by_avoid: list[str] = []
        excluded_by_diet: list[str] = []
        for recipe in tier:
            recipe_id = recipe.get("recipe_id") or recipe.get("id")
            if not recipe_id:
                continue
            match_data = await _match_ingredients(
                runtime,
                recipe_id,
                ingredient_names,
                list(getattr(unified, "dietary_restrictions", None) or []),
                [*avoid_terms, *disliked_terms],  # a disliked ingredient is no acceptable substitute either
            )
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
                }
            )
            entry = scored[-1]
            # Code-level enforcement of avoid lists: a recipe containing an
            # avoided ingredient (or named as an avoided dish) is never
            # recommendable, whatever the reasoning model would have chosen.
            avoided = [
                *avoid_ingredient_hits(avoid_terms, _recipe_ingredient_names(entry)),
                *avoid_dish_hits(avoid_dishes, str(recipe.get("name") or "")),
            ]
            if avoided:
                scored.pop()
                excluded_by_avoid.append(f"{recipe.get('name')} ({', '.join(avoided)})")
                continue
            # Dietary restrictions the corpus has no tag for are enforced here, on the ingredient
            # list so they exclude instead of refusing.
            diet_hits = violated_ingredient_restrictions(split.ingredient, _recipe_ingredient_names(entry))
            if diet_hits:
                scored.pop()
                excluded_by_diet.append(f"{recipe.get('name')} ({'; '.join(diet_hits)})")
                continue
            entry["protein_match"] = (
                names_include_protein(_recipe_ingredient_names(entry), protein_pref) if protein_pref else None
            )
            # Computed once and stored: the repetition re-score below must apply the
            # same terms, or the nudge silently vanishes for the top candidates.
            entry["time_fit"] = (
                default_time is not None
                and bool(entry["can_cook"])
                and isinstance(entry.get("cook_time_minutes"), int)
                and entry["cook_time_minutes"] <= default_time
            )
            entry["composite_score"] = _composite_score(
                match_score,
                uses_expiring,
                cuisine_score,
                0.0,
                bool(critical_missing),
                protein_lift=bool(entry["protein_match"]) and bool(entry["can_cook"]),
                time_fit=entry["time_fit"],
            )
            if stream is not None:
                stream.emit(
                    "recipe_match",
                    recipe_id=recipe_id,
                    name=recipe.get("name"),
                    match_score=match_score,
                    can_cook=match_data.get("can_cook"),
                )
        if excluded_by_diet:
            messages.append(
                f"[{NODE_NAME}] Excluded {len(excluded_by_diet)} candidate(s) that break a dietary "
                f"restriction: {'; '.join(excluded_by_diet[:5])}."
            )
        if excluded_by_avoid:
            messages.append(
                f"[{NODE_NAME}] Excluded {len(excluded_by_avoid)} candidate(s) containing something you "
                f"asked to avoid: {'; '.join(excluded_by_avoid[:5])}."
            )
        excluded_by_dislike: list[str] = []
        if disliked_terms:
            for entry in scored:
                entry["disliked_hits"] = avoid_ingredient_hits(
                    disliked_terms, _recipe_ingredient_names(entry)
                )
            has_clean_cookable = any(e.get("can_cook") and not e["disliked_hits"] for e in scored)
            flagged = [e for e in scored if e["disliked_hits"]]
            if flagged and has_clean_cookable:
                # A dislike is weaker than an allergy: it removes a recipe only while something else you can
                # cook remains. (If every cookable option contains it, they stay, flagged and disclosed.)
                excluded_by_dislike = [f"{e.get('name')} ({', '.join(e['disliked_hits'])})" for e in flagged]
                scored = [e for e in scored if not e["disliked_hits"]]
                messages.append(
                    f"[{NODE_NAME}] Left out {len(flagged)} candidate(s) containing something you dislike: "
                    f"{'; '.join(excluded_by_dislike[:5])}."
                )
            elif flagged:
                messages.append(
                    f"[{NODE_NAME}] Every cookable option contains something you dislike "
                    f"({', '.join(sorted({h for e in flagged for h in e['disliked_hits']}))}); keeping them "
                    "rather than recommending nothing."
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
                protein_lift=bool(entry["protein_match"]) and bool(entry["can_cook"]),
                time_fit=entry["time_fit"],
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
        return {
            "matched_recipes": scored,
            "dietary_exclusions": [*excluded_by_diet, *excluded_by_avoid, *excluded_by_dislike],
            "stream_messages": messages,
        }
    except Exception:
        logger.error("match_rank_unexpected_failure", exc_info=True)
        messages.append(f"[{NODE_NAME}] Ranking failed unexpectedly.")
        return {"matched_recipes": [], "stream_messages": messages}
