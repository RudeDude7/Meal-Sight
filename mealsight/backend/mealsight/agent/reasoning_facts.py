"""Factual reasoning dimensions, rendered from data the pipeline already holds.

The reasoning step used to ask a model to write all six dimensions in prose,
and the failures were all in what it synthesized (attributing pantry items to
a recipe that doesn't contain them, false "the only recipe that..."
comparisons, wrong numbers), never in what it quoted. So the four factual
dimensions (ingredient match, freshness, nutrition, context) are composed
here, deterministically, from the candidate's match data, the pantry's
expiry data, the nutrition figures and the stated constraints. Variety and
taste are judgments, but everything the user sees under them (what was
eaten recently, what preference scores exist) is rendered here too; the
model's weighing of them reaches the user only as a verified priority in
the summary sentence.

Every function returns {"applies": bool, "reasoning": str, "source": ...},
the shape the frontend already renders, plus the additive "source" key.
"""

from __future__ import annotations

from typing import Any

from mealsight.matching.avoid import ingredient_hits
from mealsight.matching.cuisine import cuisines_match, lookup_cuisine_score
from mealsight.matching.diet import (
    INGREDIENT_ENFORCED,
    TAG_BACKED,
    UNENFORCED,
    ingredient_violations,
)
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.protein import (
    is_general_protein_request,
    names_include_protein,
    protein_members,
)

SOURCE_DATA = "data"


def describe_expiry(days_remaining: Any) -> str | None:
    """Stored days_remaining is negative once an item is past its estimated
    shelf life (pantry.expiring sorts those first on purpose). Printed raw
    as "-49 day(s) left" a model reads the 49 and drops the sign."""
    if not isinstance(days_remaining, int | float):
        return None
    days = int(days_remaining)
    if days < 0:
        return f"expired {abs(days)} day(s) ago"
    if days == 0:
        return "expires today"
    return f"expires in {days} day(s)"


def item_names(items: Any, key: str = "name") -> list[str]:
    names: list[str] = []
    for item in items or []:
        name = item.get(key) if isinstance(item, dict) else str(item)
        if isinstance(name, str) and name not in names:
            names.append(name)
    return names


def names_with_importance(items: Any) -> list[str]:
    parts: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                text = f"{name} ({item['importance']})" if item.get("importance") else name
                if text not in parts:
                    parts.append(text)
        else:
            parts.append(str(item))
    return parts


def expiring_used_by(recipe: dict[str, Any], expiring_by_name: dict[str, Any]) -> list[str]:
    """The recipe's own ingredients that are also on the expiring list, each
    with its expiry in words. Same exact-name rule match_rank uses to set
    uses_expiring_ingredient, so the flag and this list can never disagree."""
    used: list[str] = []
    for name in item_names(recipe.get("matched_items")):
        if name.lower() in expiring_by_name:
            expiry = describe_expiry(expiring_by_name[name.lower()])
            used.append(f"{name} ({expiry})" if expiry else name)
    return used


def cook_time_fact(cook_time: Any, max_cook_time: int | None, usual: int | None = None) -> str:
    if not isinstance(cook_time, int | float):
        return "Cook time is not recorded for this recipe."
    if not max_cook_time and usual:
        if cook_time <= usual:
            return f"Takes {cook_time} min, within your usual ~{usual} minutes."
        return f"Takes {cook_time} min, longer than your usual ~{usual} minutes (a preference, not a limit)."
    if not max_cook_time:
        return f"Takes {cook_time} min."
    if cook_time <= max_cook_time:
        return f"Takes {cook_time} min, within your {max_cook_time}-minute limit."
    over = int(cook_time) - max_cook_time
    return (
        f"Takes {cook_time} min, which EXCEEDS your {max_cook_time}-minute limit by {over} min "
        "(the search had to relax the limit to find anything)."
    )


def ingredient_match_dimension(
    recipe: dict[str, Any], waste_by_name: dict[str, Any] | None = None
) -> dict[str, Any]:
    have = item_names(recipe.get("matched_items"))
    substitutes = [
        f"{i.get('original')} (you have {i.get('substitute')} instead)"
        for i in recipe.get("substitutable_items") or []
        if isinstance(i, dict)
    ]
    partials = [
        f"{i.get('name')} (you only have {i.get('pantry_match')})"
        for i in recipe.get("partial_matches") or []
        if isinstance(i, dict)
    ]
    missing = names_with_importance(recipe.get("missing_items"))
    total = len(have) + len(substitutes) + len(partials) + len(missing)

    sentences = [f"You have {len(have)} of this recipe's {total} ingredients: {', '.join(have) or 'none'}."]
    if substitutes:
        sentences.append(f"Covered by a substitute: {', '.join(substitutes)}.")
    if partials:
        sentences.append(f"Only a less specific form on hand: {', '.join(partials)}.")
    sentences.append(f"Missing: {', '.join(missing)}." if missing else "Nothing is missing.")
    # Missing only because the pantry's copy is long past its shelf life.
    discarded = [
        f"{name} ({describe_expiry(days)})"
        for name in item_names(recipe.get("missing_items"))
        for key, days in (waste_by_name or {}).items()
        if normalize_ingredient(name) == normalize_ingredient(key)
    ]
    if discarded:
        sentences.append(
            f"Not counted as on hand: your pantry lists {', '.join(discarded)}, too far past its "
            "shelf life to use."
        )
    critical = (
        item_names(recipe.get("critical_missing"), key="name") if recipe.get("critical_missing") else []
    )
    if critical:
        sentences.append(f"Critical missing: {', '.join(critical)}.")
    score = recipe.get("match_score")
    verdict = "can be cooked with what you have" if recipe.get("can_cook") else "cannot be cooked as-is"
    sentences.append(f"Ingredient match score {score}; it {verdict}.")
    return {"applies": True, "reasoning": " ".join(sentences), "source": SOURCE_DATA}


def freshness_dimension(
    recipe: dict[str, Any], expiring_by_name: dict[str, Any], waste_by_name: dict[str, Any]
) -> dict[str, Any]:
    used = expiring_used_by(recipe, expiring_by_name)
    sentences: list[str] = []
    if used:
        sentences.append(
            f"Uses {len(used)} pantry item(s) at or near the end of their shelf life: {', '.join(used)}."
        )
    else:
        sentences.append("Uses none of the pantry items that are close to expiring.")
    # An item far past its shelf life is waste, not a freshness win, but if
    # the recipe depends on one the cook must be told to check it first.
    stale = [
        f"{name} ({describe_expiry(waste_by_name[name.lower()])})"
        for name in item_names(recipe.get("matched_items"))
        if name.lower() in waste_by_name
    ]
    if stale:
        sentences.append(
            f"Check before cooking: your pantry lists {', '.join(stale)}, well past their estimated "
            "shelf life; discard anything that has spoiled."
        )
    return {"applies": bool(used), "reasoning": " ".join(sentences), "source": SOURCE_DATA}


def nutrition_dimension(recipe: dict[str, Any]) -> dict[str, Any]:
    nutrition = recipe.get("nutrition_info")
    if not isinstance(nutrition, dict):
        return {
            "applies": False,
            "reasoning": "No nutrition figures were calculated for this recipe.",
            "source": SOURCE_DATA,
        }
    fields = [
        ("calories", "kcal", "kcal"),
        ("protein_g", "protein", "g"),
        ("carbs_g", "carbs", "g"),
        ("fat_g", "fat", "g"),
        ("fiber_g", "fiber", "g"),
        ("sodium_mg", "sodium", "mg"),
    ]
    parts = []
    for key, label, unit in fields:
        if key in nutrition:
            parts.append(f"{nutrition[key]} kcal" if label == "kcal" else f"{nutrition[key]} {unit} {label}")
    servings = nutrition.get("servings")
    basis = f"Per serving (recipe sized for {servings} serving(s))" if servings else "Per serving"
    sentences = [f"{basis}: {', '.join(parts)}."]
    coverage = nutrition.get("coverage_note") or nutrition.get("coverage_pct")
    if coverage:
        sentences.append(str(coverage))
    tags = nutrition.get("tags")
    if tags:
        sentences.append(f"Tagged: {', '.join(str(t).replace('_', ' ') for t in tags)}.")
    return {"applies": True, "reasoning": " ".join(sentences), "source": SOURCE_DATA}


def _recipe_ingredient_names(recipe: dict[str, Any]) -> list[str]:
    names = item_names(recipe.get("matched_items")) + item_names(recipe.get("missing_items"))
    names += item_names(recipe.get("partial_matches")) + item_names(
        recipe.get("substitutable_items"), key="original"
    )
    return names


def context_dimension(
    recipe: dict[str, Any],
    unified: Any,
    context_signals: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    pantry_names: list[str] | None = None,
) -> dict[str, Any]:
    sentences = [
        cook_time_fact(
            recipe.get("cook_time_minutes"),
            getattr(unified, "stated_max_cook_time_minutes", None),
            getattr(unified, "max_cook_time_minutes", None)
            if getattr(unified, "max_cook_time_is_default", False)
            else None,
        )
    ]
    servings = getattr(unified, "servings", None)
    if servings:
        sentences.append(f"Sized for {servings} serving(s).")
    meal_type = context_signals.get("meal_type")
    if meal_type:
        sentences.append(f"Meal type right now: {meal_type}.")
    complexity = context_signals.get("complexity_suggestion")
    if complexity:
        sentences.append(str(complexity))

    cuisine_asked = getattr(unified, "cuisine_preference", None)
    cuisine = recipe.get("cuisine")
    if cuisine_asked:
        if isinstance(cuisine, str) and cuisines_match(str(cuisine_asked), cuisine):
            sentences.append(f"Cuisine: {cuisine}, as you asked.")
        else:
            sentences.append(
                f"You asked for {cuisine_asked} cuisine; this recipe is {cuisine}, "
                "so that request is not met."
            )

    protein = getattr(unified, "protein_preference", None)
    if protein:
        sentences.append(_protein_fact(str(protein), recipe))
        if protein_met(str(protein), recipe) is False and not is_general_protein_request(str(protein)):
            sentences.append(protein_shortfall_note(str(protein), candidates or [], pantry_names or []))

    sentences.extend(dietary_facts(recipe, list(getattr(unified, "dietary_restrictions", None) or [])))

    avoid = [a for a in (getattr(unified, "avoid_ingredients", None) or []) if a]
    if avoid:
        present = {normalize_ingredient(n) for n in _recipe_ingredient_names(recipe)}
        hits = [a for a in avoid if normalize_ingredient(a) in present]
        if hits:
            sentences.append(f"WARNING: contains an ingredient you asked to avoid: {', '.join(hits)}.")
        else:
            sentences.append(f"None of this recipe's ingredients is on your avoid list ({', '.join(avoid)}).")
    return {"applies": True, "reasoning": " ".join(sentences), "source": SOURCE_DATA}


def dietary_facts(recipe: dict[str, Any], restrictions: list[str]) -> list[str]:
    """One sentence per restriction, stating how it was actually checked
    (mealsight.matching.diet). A restriction with no corpus tag is never
    reported as "not tagged": that would be true of every recipe and say
    nothing. And a restriction the system cannot check is said to be
    unenforced, not implied to be met."""
    tags = {str(t) for t in recipe.get("dietary_tags") or []}
    names = _recipe_ingredient_names(recipe)
    sentences: list[str] = []
    for restriction in restrictions:
        if restriction in TAG_BACKED:
            has = restriction.replace("-", "_") in tags
            sentences.append(
                f"Dietary restriction {restriction}: this recipe "
                f"{'carries' if has else 'does NOT carry'} the {restriction} tag."
            )
        elif restriction in INGREDIENT_ENFORCED:
            problems = ingredient_violations(restriction, names)
            if problems:
                sentences.append(f"WARNING: breaks your {restriction} restriction: {', '.join(problems)}.")
            else:
                limit = INGREDIENT_ENFORCED[restriction].limitation
                sentences.append(
                    f"Dietary restriction {restriction}: none of this recipe's {len(names)} ingredients "
                    f"matched what {restriction} excludes. {limit}".strip()
                )
        else:
            reason = UNENFORCED.get(restriction, "The system cannot verify it.")
            sentences.append(f"NOT ENFORCED: {restriction}. {reason} This recipe may not meet it.")
    return sentences


def protein_met(protein: str, recipe: dict[str, Any]) -> bool | None:
    """Whether the recipe satisfies the protein request, or None when there
    is not enough data to say (a general "high-protein" ask with no
    nutrition figures)."""
    lowered = protein.lower()
    if "protein" in lowered:  # a general preference such as "high-protein"
        nutrition = recipe.get("nutrition_info")
        tags = nutrition.get("tags") if isinstance(nutrition, dict) else None
        return ("high_protein" in tags) if isinstance(tags, list) else None
    return names_include_protein(_recipe_ingredient_names(recipe), protein)


def protein_shortfall_note(
    protein: str,
    candidates: list[dict[str, Any]],
    pantry_names: list[str],
) -> str:
    """Said when the chosen recipe does not meet a specific protein
    preference: whether that is because nothing cookable does, and whether
    the pantry has any of it at all. Never lets a substitute pass as the
    thing asked for."""
    considered = len(candidates)
    cookable_with = [c for c in candidates if c.get("can_cook") and protein_met(protein, c)]
    if cookable_with:
        names = ", ".join(str(c.get("name")) for c in cookable_with[:2])
        return f"A cookable recipe with {protein} was available ({names}); it did not win overall."
    members = protein_members(protein)
    from mealsight.matching.protein import ingredient_is_protein

    has_any = any(ingredient_is_protein(n, members) for n in pantry_names)
    if has_any:
        return (
            f"None of the {considered} recipes considered that include {protein} can be cooked with what "
            "you have, so this recipe does not meet that preference; it is the best cookable option."
        )
    return (
        f"Your pantry has no {protein}, so no recipe built around it is cookable right now. This recipe "
        f"does not meet that preference; it is the best cookable option among the {considered} considered."
    )


def _protein_fact(protein: str, recipe: dict[str, Any]) -> str:
    met = protein_met(protein, recipe)
    if "protein" in protein.lower():
        if met is None:
            return f"Protein preference ({protein}): no nutrition figures were calculated to check it."
        negation = "" if met else "not "
        return f"Protein preference ({protein}): this recipe is {negation}tagged high protein."
    if met:
        return f"Protein preference ({protein}): the recipe includes {protein}."
    return f"Protein preference ({protein}): none of this recipe's ingredients is {protein}."


def variety_dimension(recipe: dict[str, Any], meal_history: list[dict[str, Any]]) -> dict[str, Any]:
    recent = [
        str(m.get("recipe_name") or m.get("name"))
        for m in meal_history
        if m.get("recipe_name") or m.get("name")
    ]
    repetition = recipe.get("repetition_recommendation")
    if not recent and not repetition:
        return {
            "applies": False,
            "reasoning": "No recent meals are on record, so variety is not a factor.",
            "source": SOURCE_DATA,
        }
    sentences = [f"Recent meals: {', '.join(recent)}." if recent else "No recent meals are on record."]
    if repetition:
        sentences.append(
            f"Repetition check for this recipe: {repetition} (score {recipe.get('repetition_score')})."
        )
    return {"applies": True, "reasoning": " ".join(sentences), "source": SOURCE_DATA}


def taste_dimension(recipe: dict[str, Any], user_profile: dict[str, Any]) -> dict[str, Any]:
    scores = user_profile.get("cuisine_preferences") or {}
    disliked = [str(d) for d in (user_profile.get("disliked_ingredients") or [])]
    if not scores and not disliked:
        return {
            "applies": False,
            "reasoning": "No taste or cuisine preferences are on file.",
            "source": SOURCE_DATA,
        }
    sentences: list[str] = []
    if scores:
        listed = ", ".join(f"{k} {v}" for k, v in scores.items())
        cuisine = recipe.get("cuisine")
        raw_score = lookup_cuisine_score(scores, cuisine if isinstance(cuisine, str) else None, -1.0)
        score: float | None = None if raw_score < 0 else raw_score
        sentences.append(f"Cuisine preference scores on file: {listed}.")
        sentences.append(
            f"This recipe is {cuisine}, scored {score}."
            if score is not None
            else f"This recipe is {cuisine}, which has no score on file."
        )
    if disliked:
        hits = ingredient_hits(disliked, _recipe_ingredient_names(recipe))
        sentences.append(
            f"WARNING: contains an ingredient you dislike ({', '.join(hits)}); "
            "no cookable alternative was found."
            if hits
            else f"Contains none of your disliked ingredients ({', '.join(disliked)})."
        )
    return {"applies": True, "reasoning": " ".join(sentences), "source": SOURCE_DATA}


def compose_reasoning(
    recipe: dict[str, Any],
    *,
    unified: Any,
    expiring_items: list[dict[str, Any]],
    waste_candidates: list[dict[str, Any]],
    user_profile: dict[str, Any],
    meal_history: list[dict[str, Any]],
    context_signals: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    pantry_names: list[str] | None = None,
) -> dict[str, Any]:
    expiring_by_name = {
        str(i["name"]).lower(): i.get("days_remaining") for i in expiring_items if i.get("name")
    }
    waste_by_name = {
        str(i["name"]).lower(): -abs(int(i.get("days_overdue", 0))) for i in waste_candidates if i.get("name")
    }
    return {
        "ingredient_match_reasoning": ingredient_match_dimension(recipe, waste_by_name),
        "freshness_reasoning": freshness_dimension(recipe, expiring_by_name, waste_by_name),
        "nutrition_reasoning": nutrition_dimension(recipe),
        "variety_reasoning": variety_dimension(recipe, meal_history),
        "context_reasoning": context_dimension(recipe, unified, context_signals, candidates, pantry_names),
        "taste_reasoning": taste_dimension(recipe, user_profile),
    }
