"""Dimension 2 — constraint satisfaction. Safety-critical: a dietary
violation is real harm, not a quality miss.

Runs the real, full 11-node agent pipeline (mealsight.agent.runner.
run_recommendation) for every case in eval.cases, via natural-language
text_input — the real extraction step is exercised too, not bypassed.
Hard constraints (dietary restrictions, cook time, avoid-ingredients,
avoid-dishes, servings) are checked against what the pipeline itself
extracted (final_state["unified_request"]) and what it actually
recommended (final_state["top_recommendation"] cross-referenced against
final_state["matched_recipes"]) — no extra API call needed, since
match_rank already attaches dietary_tags/cook_time_minutes/cuisine plus
matched_items/missing_items/partial_matches to every candidate.

Honest refusal (top_recommendation["available"] is False) PASSES when
the case was authored as unsatisfiable (Case.expect_refusal), and FAILS
when it wasn't — the system talked itself out of a real, satisfiable
request. A recommendation that violates any hard constraint always
fails, regardless of expect_refusal. avoid_ingredients/avoid_dishes are
NOT currently enforced as a hard filter anywhere in the real pipeline
(search_recipes has no such parameters; reason.py only ever passes them
to the reasoning LLM as prose guidance) — real violations on those two
constraint types are an expected, reportable finding of this dimension,
not a bug in the eval itself.

Zero pantry risk: generate_output (node 9) never calls remove_items;
pantry deduction only happens through a separate, later, user-confirmed
cook flow outside this graph entirely.
"""

from __future__ import annotations

import json
import time
from typing import Any

from eval.cases import CASES, Case
from eval.matching import normalize_words
from eval.models import CaseResult, DimensionResult, Violation
from mealsight.agent.mcp_client import MCPClientManager
from mealsight.agent.runner import run_recommendation
from mealsight.agent.state import MealSightState
from mealsight.config.settings import settings
from mealsight.matching.cuisine import cuisines_match
from mealsight.providers import get_text_provider

NAME = "dimension2_constraint_satisfaction"
PASS_THRESHOLD = 1.0  # hard constraints are binary; any real violation should surface
# Soft constraints (cuisine now; protein when a case sets one) are scored on
# their own, never mixed into the hard verdict. At least half of the soft-scored
# cases must land. Fixed before the first full run and not revisited after it.
SOFT_PASS_THRESHOLD = 0.5

# Every third case (always including both intentionally-unsatisfiable
# ones, d2_10 and d2_15) — a routine, cheap check; release runs use the
# full 30 via sampled=False.
SAMPLED_CASE_IDS = frozenset({c.case_id for i, c in enumerate(CASES) if i % 3 == 0} | {"d2_10", "d2_15"})


# Allergen/category words that name no ingredient literally: avoiding one
# means avoiding every member. Likewise cilantro/coriander, one herb with a
# US and a UK name.
AVOID_GROUPS: dict[str, frozenset[str]] = {
    "shellfish": frozenset(
        {
            "shrimp",
            "prawn",
            "crab",
            "lobster",
            "clam",
            "mussel",
            "oyster",
            "scallop",
            "crayfish",
            "langoustine",
        }
    ),
    "seafood": frozenset(
        {
            "shrimp",
            "prawn",
            "crab",
            "lobster",
            "clam",
            "mussel",
            "oyster",
            "scallop",
            "crayfish",
            "langoustine",
            "fish",
            "salmon",
            "tuna",
            "cod",
            "haddock",
            "mackerel",
            "trout",
            "anchovy",
            "sardine",
            "squid",
            "octopus",
        }
    ),
    "nut": frozenset({"almond", "walnut", "cashew", "pecan", "hazelnut", "pistachio", "macadamia", "peanut"}),
    "dairy": frozenset({"milk", "cheese", "butter", "cream", "yogurt", "yoghurt", "ghee"}),
    "cilantro": frozenset({"coriander"}),
    "coriander": frozenset({"cilantro"}),
}


def _all_ingredient_names(match_data: dict[str, Any]) -> list[str]:
    """Every ingredient the recipe needs, whichever bucket the matcher put
    it in. A substitutable item is still a recipe ingredient (its original),
    so it counts here too."""
    names: list[str] = []
    for key, name_key in (
        ("matched_items", "name"),
        ("missing_items", "name"),
        ("partial_matches", "name"),
        ("substitutable_items", "original"),
    ):
        for item in match_data.get(key) or []:
            name = item.get(name_key) if isinstance(item, dict) else None
            if isinstance(name, str):
                names.append(name)
    return names


def _contains_run(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def ingredient_hits(avoid_terms: list[str], ingredient_names: list[str]) -> list[str]:
    """Which avoid terms the recipe's ingredients violate. Matching is by
    whole words, never substrings: 'peanuts' hits 'peanut butter', 'olives'
    hits 'black olives', 'shellfish' hits 'king prawns' (via AVOID_GROUPS),
    but 'egg' does not hit 'eggplant' nor 'nut' 'coconut'."""
    ingredient_words = [normalize_words(n) for n in ingredient_names]
    hits: list[str] = []
    for term in avoid_terms:
        term_words = normalize_words(term)
        if not term_words:
            continue
        members = [[w] for w in AVOID_GROUPS.get(" ".join(term_words), frozenset())]
        candidates = [term_words, *members]
        if any(_contains_run(words, candidate) for words in ingredient_words for candidate in candidates):
            hits.append(term)
    return hits


def dish_hits(avoid_dishes: list[str], recipe_name: str) -> list[str]:
    """Avoided dishes the recipe name matches as whole words: 'salad' hits
    'Greek Salad', 'stir fry' hits 'Beef Stir-Fry', 'tea' never hits 'Steak'."""
    name_words = normalize_words(recipe_name)
    return [d for d in avoid_dishes if _contains_run(name_words, normalize_words(d))]


# Restrictions the corpus has no tag for are checked here against ingredient lists. These term lists
# are this scorer's OWN copy, deliberately not imported from mealsight.matching.diet, so the scorer
# stays an independent check on the production filter instead of mirroring it.
_TAG_BACKED = frozenset({"vegetarian", "vegan", "dairy_free", "gluten_free", "nut_free"})
_PORK = ["pork", "bacon", "ham", "lard", "pancetta", "prosciutto", "chorizo", "gammon", "sausage", "salami"]
_SHELLFISH = [
    "shellfish",
    "shrimp",
    "prawn",
    "crab",
    "lobster",
    "clam",
    "mussel",
    "oyster",
    "scallop",
    "crayfish",
    "langoustine",
    "scampi",
]
_MEAT = [
    "beef",
    "pork",
    "lamb",
    "veal",
    "mutton",
    "venison",
    "chicken",
    "turkey",
    "duck",
    "goose",
    "bacon",
    "ham",
    "sausage",
    "mince",
    "steak",
    "lard",
    "gelatin",
    "meat",
    "chorizo",
    "salami",
    "brisket",
]
_ALCOHOL = [
    "wine",
    "beer",
    "rum",
    "brandy",
    "whisky",
    "whiskey",
    "vodka",
    "sherry",
    "liqueur",
    "cider",
    "sake",
    "vermouth",
    "bourbon",
    "cognac",
    "champagne",
    "prosecco",
    "stout",
    "lager",
    "mirin",
]
_DAIRY = ["milk", "cheese", "butter", "cream", "yogurt", "yoghurt", "ghee"]
_INGREDIENT_RESTRICTIONS: dict[str, list[str]] = {
    "peanut_free": ["peanut", "groundnut"],
    "shellfish_free": _SHELLFISH,
    "soy_free": ["soy", "soya", "tofu", "tempeh", "edamame", "miso", "tamari"],
    "egg_free": ["egg", "mayonnaise", "mayo", "meringue"],
    "pescatarian": _MEAT,
    "halal": _PORK + _ALCOHOL,
    "kosher": _PORK + _SHELLFISH,
}
# A restriction the system says it cannot check must be DISCLOSED in the answer, never silently dropped.
_DISCLOSED = frozenset({"low_sodium", "low_fat", "low_carb", "keto", "paleo"})
# Partial checks must also say what they do not cover.
_MUST_STATE_LIMIT = {"halal": "certification", "kosher": "certification"}


def restriction_violations(restriction: str, ingredient_names: list[str]) -> list[str]:
    terms = _INGREDIENT_RESTRICTIONS.get(restriction)
    if terms is None:
        return []
    names = [n for n in ingredient_names if "vinegar" not in n.lower()]
    found = ingredient_hits(terms, names)
    if restriction == "kosher" and ingredient_hits(_MEAT, names) and ingredient_hits(_DAIRY, names):
        found.append("meat together with dairy")
    return found


def _find_recipe(final_state: MealSightState, recipe_id: str) -> dict[str, Any] | None:
    for recipe in final_state.get("matched_recipes") or []:
        if recipe.get("id") == recipe_id:
            return recipe
    return None


def _constraints_in_force(case: Case, extracted: Any) -> dict[str, Any]:
    """The union of what the case author wrote and what the pipeline
    extracted. Checking only the pipeline's own extraction would let a
    dropped restriction pass its own violation."""
    dietary = {r.replace("-", "_") for r in case.dietary}
    avoid_ingredients = list(case.avoid_ingredients)
    avoid_dishes = list(case.avoid_dishes)
    # Only a limit the user stated is a constraint. A profile-default time
    # (max_cook_time_is_default) is a preference the pipeline ranks by; counting
    # it here would fail correct recommendations and pass wrong refusals.
    extracted_limit = getattr(extracted, "stated_max_cook_time_minutes", None)
    limits = [m for m in (case.max_minutes, extracted_limit) if m is not None]
    servings = case.servings if case.servings is not None else getattr(extracted, "servings", None)
    if extracted is not None:
        dietary |= {r.replace("-", "_") for r in extracted.dietary_restrictions}
        avoid_ingredients += [a for a in extracted.avoid_ingredients if a not in avoid_ingredients]
        avoid_dishes += [d for d in extracted.avoid_dishes if d not in avoid_dishes]
    return {
        "dietary": sorted(dietary),
        "max_minutes": min(limits) if limits else None,
        "servings": servings,
        "avoid_ingredients": avoid_ingredients,
        "avoid_dishes": avoid_dishes,
        "cuisine_soft": case.cuisine_soft,
        "extracted_by_pipeline": {
            "dietary": list(getattr(extracted, "dietary_restrictions", []) or []),
            "max_minutes": extracted_limit,
            "servings": getattr(extracted, "servings", None),
            "avoid_ingredients": list(getattr(extracted, "avoid_ingredients", []) or []),
            "avoid_dishes": list(getattr(extracted, "avoid_dishes", []) or []),
            "cuisine": getattr(extracted, "cuisine_preference", None),
            "protein": getattr(extracted, "protein_preference", None),
        },
    }


def _check_case(case: Case, final_state: MealSightState) -> CaseResult:
    unified = final_state.get("unified_request")
    top = final_state.get("top_recommendation") or {}
    available = bool(top.get("available"))
    actual_refusal = not available
    checked = _constraints_in_force(case, unified)

    if actual_refusal:
        passed = case.expect_refusal
        notes = (
            "correctly refused an unsatisfiable request"
            if passed
            else "refused a request the eval expected to be satisfiable"
        )
        return CaseResult(
            case_id=case.case_id,
            description=case.description,
            text_input=case.text_input,
            expect_refusal=case.expect_refusal,
            actual_refusal=True,
            passed=passed,
            violations=[],
            soft_score=None,
            recipe_id=None,
            recipe_name=None,
            notes=notes,
            constraints_checked=checked,
        )

    recipe_id = top.get("recipe_id")
    recipe = _find_recipe(final_state, recipe_id) if isinstance(recipe_id, str) else None
    recipe_name = recipe.get("name") if recipe else None
    violations: list[Violation] = []

    if case.expect_refusal:
        violations.append(
            Violation(
                case_id=case.case_id,
                constraint="expected_refusal",
                detail="Case was authored as unsatisfiable, but the pipeline recommended a recipe anyway.",
                recommended_recipe_id=recipe_id,
                recommended_recipe_name=recipe_name,
            )
        )

    dietary = set(checked["dietary"])
    avoid_ingredients = list(checked["avoid_ingredients"])
    avoid_dishes = list(checked["avoid_dishes"])
    max_minutes = checked["max_minutes"]
    servings = checked["servings"]

    if recipe is not None:
        recipe_tags = set(recipe.get("dietary_tags") or [])
        ingredient_names = _all_ingredient_names(recipe)
        for restriction in sorted(dietary & set(_INGREDIENT_RESTRICTIONS)):
            for bad in restriction_violations(restriction, ingredient_names):
                violations.append(
                    Violation(
                        case_id=case.case_id,
                        constraint=f"dietary_restriction:{restriction}",
                        detail=f"Recipe '{recipe_name}' breaks {restriction}: contains '{bad}'.",
                        recommended_recipe_id=recipe_id,
                        recommended_recipe_name=recipe_name,
                    )
                )
        answer_text = json.dumps(top, default=str)
        for restriction in sorted(dietary & _DISCLOSED):
            if "NOT ENFORCED" not in answer_text or restriction.replace("_", "-") not in answer_text:
                violations.append(
                    Violation(
                        case_id=case.case_id,
                        constraint=f"disclosure:{restriction}",
                        detail=f"'{restriction}' cannot be enforced, but the answer does not say so.",
                        recommended_recipe_id=recipe_id,
                        recommended_recipe_name=recipe_name,
                    )
                )
        for restriction, phrase in _MUST_STATE_LIMIT.items():
            if restriction in dietary and phrase not in answer_text:
                violations.append(
                    Violation(
                        case_id=case.case_id,
                        constraint=f"disclosure:{restriction}",
                        detail=f"'{restriction}' is only partly checkable, but the answer never says "
                        f"what the check does not cover (expected the word '{phrase}').",
                        recommended_recipe_id=recipe_id,
                        recommended_recipe_name=recipe_name,
                    )
                )
        for missing_tag in sorted((dietary & _TAG_BACKED) - recipe_tags):
            violations.append(
                Violation(
                    case_id=case.case_id,
                    constraint=f"dietary_restriction:{missing_tag}",
                    detail=f"Recipe '{recipe_name}' is missing required dietary tag '{missing_tag}' "
                    f"(has: {sorted(recipe_tags)}).",
                    recommended_recipe_id=recipe_id,
                    recommended_recipe_name=recipe_name,
                )
            )

        cook_time = recipe.get("cook_time_minutes")
        if max_minutes is not None and isinstance(cook_time, int) and cook_time > max_minutes:
            violations.append(
                Violation(
                    case_id=case.case_id,
                    constraint="max_cook_time_minutes",
                    detail=f"Recipe '{recipe_name}' takes {cook_time} minutes, exceeding the stated "
                    f"limit of {max_minutes}.",
                    recommended_recipe_id=recipe_id,
                    recommended_recipe_name=recipe_name,
                )
            )

        if servings is not None:
            scaled = final_state.get("scaled_recipe") or {}
            target_servings = scaled.get("target_servings")
            if isinstance(target_servings, int) and target_servings != servings:
                violations.append(
                    Violation(
                        case_id=case.case_id,
                        constraint="servings",
                        detail=f"Recipe was scaled to {target_servings} servings, not the requested "
                        f"{servings}.",
                        recommended_recipe_id=recipe_id,
                        recommended_recipe_name=recipe_name,
                    )
                )

        for bad in ingredient_hits(avoid_ingredients, _all_ingredient_names(recipe)):
            violations.append(
                Violation(
                    case_id=case.case_id,
                    constraint=f"avoid_ingredients:{bad}",
                    detail=f"Recipe '{recipe_name}' uses '{bad}', which was on the avoid list.",
                    recommended_recipe_id=recipe_id,
                    recommended_recipe_name=recipe_name,
                )
            )

        if recipe_name:
            for dish in dish_hits(avoid_dishes, recipe_name):
                violations.append(
                    Violation(
                        case_id=case.case_id,
                        constraint=f"avoid_dishes:{dish}",
                        detail=f"Recipe '{recipe_name}' matches an avoided dish ('{dish}').",
                        recommended_recipe_id=recipe_id,
                        recommended_recipe_name=recipe_name,
                    )
                )

    soft_score: float | None = None
    if case.cuisine_soft is not None and recipe is not None:
        cuisine = recipe.get("cuisine")
        soft_score = 1.0 if isinstance(cuisine, str) and cuisines_match(case.cuisine_soft, cuisine) else 0.0

    passed = not violations
    return CaseResult(
        case_id=case.case_id,
        description=case.description,
        text_input=case.text_input,
        expect_refusal=case.expect_refusal,
        actual_refusal=False,
        passed=passed,
        violations=violations,
        soft_score=soft_score,
        recipe_id=recipe_id,
        recipe_name=recipe_name,
        notes="ok" if passed else f"{len(violations)} hard-constraint violation(s)",
        constraints_checked=checked,
        recipe_facts=(
            {
                "dietary_tags": sorted(recipe.get("dietary_tags") or []),
                "cook_time_minutes": recipe.get("cook_time_minutes"),
                "cuisine": recipe.get("cuisine"),
                "servings_scaled_to": (final_state.get("scaled_recipe") or {}).get("target_servings"),
                "ingredients": sorted(set(_all_ingredient_names(recipe))),
            }
            if recipe is not None
            else {}
        ),
    )


def summarize_cases(case_results: list[CaseResult]) -> tuple[float, bool]:
    score = sum(1 for r in case_results if r.passed) / len(case_results) if case_results else 0.0
    # Passes only when every case passed. "No violations" is not enough: a
    # satisfiable request wrongly refused fails its case with no violation.
    return score, bool(case_results) and all(r.passed for r in case_results)


async def run_dimension2(case_limit: int | None = None, sampled: bool = False) -> DimensionResult:
    cases = [c for c in CASES if not sampled or c.case_id in SAMPLED_CASE_IDS]
    if case_limit is not None:
        cases = cases[:case_limit]

    case_results: list[CaseResult] = []
    api_calls = 0
    start = time.monotonic()

    async with MCPClientManager() as manager:
        for case in cases:
            trace_id = f"eval-dimension2-{case.case_id}"
            final_state = await run_recommendation(
                text_input=case.text_input,
                manager=manager,
                trace_id=trace_id,
            )
            api_calls += 1
            case_results.append(_check_case(case, final_state))

    wall_clock = time.monotonic() - start
    total_tokens = sum(
        int(call.get("total_tokens", 0))
        for call in get_text_provider().get_call_log()
        if isinstance(call.get("trace_id"), str) and str(call["trace_id"]).startswith("eval-dimension2-")
    )

    all_violations = [v for r in case_results for v in r.violations]
    passed_count = sum(1 for r in case_results if r.passed)
    soft_scores = [r.soft_score for r in case_results if r.soft_score is not None]
    soft_all_mean = sum(soft_scores) / len(soft_scores) if soft_scores else None
    # Headline soft score: cases where a hit was possible with this pantry. A miss
    # the pantry makes unavoidable is reported separately, not counted against it.
    attainable = {c.case_id for c in cases if c.cuisine_attainable is True}
    unattainable = {c.case_id for c in cases if c.cuisine_attainable is False}
    attainable_scores = [
        r.soft_score for r in case_results if r.case_id in attainable and r.soft_score is not None
    ]
    soft_mean = sum(attainable_scores) / len(attainable_scores) if attainable_scores else None
    honest_misses = [r.case_id for r in case_results if r.case_id in unattainable and r.soft_score == 0.0]
    unattainable_hits = [r.case_id for r in case_results if r.case_id in unattainable and r.soft_score == 1.0]
    unattainable_refused = [r.case_id for r in case_results if r.case_id in unattainable and r.actual_refusal]
    score, dimension_passed = summarize_cases(case_results)
    by_kind: dict[str, int] = {}
    for violation in all_violations:
        kind = violation.constraint.split(":")[0]
        by_kind[kind] = by_kind.get(kind, 0) + 1
    correct_refusals = [r.case_id for r in case_results if r.actual_refusal and r.expect_refusal]
    wrong_refusals = [r.case_id for r in case_results if r.actual_refusal and not r.expect_refusal]

    return DimensionResult(
        name=NAME,
        pass_threshold=PASS_THRESHOLD,
        score=score,
        passed=dimension_passed,
        metrics={
            "cases_passed": passed_count,
            "cases_total": len(case_results),
            "total_violations": len(all_violations),
            "refusal_cases_expected": sum(1 for c in cases if c.expect_refusal),
            "refusal_cases_actual": sum(1 for r in case_results if r.actual_refusal),
            "hard_constraint_violations_by_kind": by_kind,
            "correct_refusals": correct_refusals,
            "wrongly_refused_satisfiable": wrong_refusals,
            "soft_cuisine_score": soft_mean,
            "soft_cases_scored": len(attainable_scores),
            "soft_cuisine_all_cases_score": soft_all_mean,
            "soft_all_cases_scored": len(soft_scores),
            "soft_cuisine_hits_attainable": sum(1 for s in attainable_scores if s == 1.0),
            "soft_honest_misses_unattainable": honest_misses,
            "soft_unattainable_unexpected_hits": unattainable_hits,
            "soft_unattainable_refused": unattainable_refused,
            "soft_threshold": SOFT_PASS_THRESHOLD,
            "soft_passed": None if soft_mean is None else soft_mean >= SOFT_PASS_THRESHOLD,
            "soft_protein_cases": 0,
            "soft_note": "headline soft_cuisine_score = hit rate over cuisine cases the seeded pantry could "
            "satisfy (cuisine_attainable=True, cases.py); misses the pantry makes unavoidable are listed "
            "separately as soft_honest_misses_unattainable. soft_cuisine_all_cases_score is the pooled rate, "
            "comparable to the first run's 0.5. Cuisine is scored only on cases that were not refused. No "
            "case sets a protein preference, so protein is unmeasured here",
            "reasoning_model": settings.REASONING_MODEL,
            "sampled": sampled,
        },
        case_count=len(cases),
        api_calls=api_calls,
        total_tokens=total_tokens,
        wall_clock_seconds=wall_clock,
        case_results=case_results,
    )
