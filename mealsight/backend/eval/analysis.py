"""What the system COULD have done, computed independently of the ranking code.

Dimensions 4 and 5 ask whether the recommendation honours a freshness or profile signal.
That question is only fair against the set of things that were possible: a recommendation
cannot use an expiring item no cookable recipe uses, and cannot favour a cuisine none of the
cookable recipes belong to. This module computes that set for a pantry by running the matcher
(whose arithmetic Dimension 3 verified) over the WHOLE corpus, and scores each cookable
recipe with a hand-written composite.

The composite is this module's OWN copy of the documented ranking terms, written as literals
and deliberately not imported from match_rank, so the evaluation is an independent check on
the ranking and not a mirror of it:

    composite = 0.60 * match_score
              + 0.15 if the recipe uses an expiring (usable) pantry item
              + 0.15 * cuisine score (0.5 when there is no history for the cuisine)
              + 0.15 if a protein preference is stated and the recipe has it (cookable only)
              + 0.15 if the cook time is within a DEFAULTED preference (cookable only)
              - 0.10 * repetition score (1.0 exact repeat, 0.7 protein, 0.5 cuisine dominance)

A recipe that is not cookable never wins, whatever its other terms.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mealsight.db import get_recipe_db
from mealsight.matching.matcher import (
    MatchContext,
    build_match_context,
    match_recipe,
    parse_recipe_ingredients,
)
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.specificity import compare_specificity
from mealsight.matching.synonyms import resolve_canonical

W_MATCH = 0.60
W_FRESH = 0.15
W_CUISINE = 0.15
W_PROTEIN = 0.15
W_TIME_FIT = 0.15
W_REPETITION = 0.10
NEUTRAL = 0.5


@dataclass
class Candidate:
    recipe_id: str
    name: str
    cuisine: str | None
    cook_time: int | None
    ingredient_names: list[str]
    match_score: float
    can_cook: bool
    matched_names: list[str]
    uses_expiring: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    composite: float = 0.0


@dataclass
class Corpus:
    rows: list[dict[str, Any]]
    context: MatchContext


async def load_corpus() -> Corpus:
    db = get_recipe_db()
    rows = [
        {
            "id": r["id"],
            "name": r["name"].strip(),
            "cuisine": r["cuisine"],
            "cook_time": r["cook_time_minutes"],
            "tags": json.loads(r["dietary_tags"] or "[]"),
            "ingredients_json": r["ingredients"],
            "ingredient_names": [i["name"] for i in json.loads(r["ingredients"])],
        }
        for r in await db.fetch_all(
            "SELECT id, name, cuisine, cook_time_minutes, dietary_tags, ingredients FROM recipes"
        )
    ]
    context = await build_match_context(db)
    await db.close()
    return Corpus(rows, context)


def canonical(name: str, corpus: Corpus) -> str:
    return resolve_canonical(normalize_ingredient(name), corpus.context.synonym_map)


def uses_item(recipe_ingredient_names: list[str], pantry_item: str, corpus: Corpus) -> bool:
    """Whether a recipe has an ingredient line this pantry item satisfies: the same canonical
    name, or a pantry item that is a more specific cut/variety of the line (the matcher's own
    full-specificity rule). Independent of match_rank's own check."""
    have = canonical(pantry_item, corpus)
    for line in recipe_ingredient_names:
        want = canonical(line, corpus)
        if want == have or compare_specificity(want, have) == "full":
            return True
    return False


def analyse(
    corpus: Corpus,
    usable_pantry_names: list[str],
    expiring_names: list[str],
    dietary_restrictions: list[str] | None = None,
) -> list[Candidate]:
    """Every recipe in the corpus matched against the pantry, flagged for expiring-item use."""
    out: list[Candidate] = []
    for row in corpus.rows:
        result = match_recipe(
            parse_recipe_ingredients(row["ingredients_json"]),
            usable_pantry_names,
            corpus.context.substitution_map,
            corpus.context.synonym_map,
            dietary_restrictions,
        )
        cand = Candidate(
            recipe_id=row["id"],
            name=row["name"],
            cuisine=row["cuisine"],
            cook_time=row["cook_time"],
            ingredient_names=row["ingredient_names"],
            match_score=result.match_score,
            can_cook=result.can_cook,
            matched_names=[m.name for m in result.matched_items],
            tags=row.get("tags", []),
        )
        if result.can_cook:
            cand.uses_expiring = [e for e in expiring_names if uses_item(row["ingredient_names"], e, corpus)]
        out.append(cand)
    return out


def composite(
    cand: Candidate,
    *,
    cuisine_scores: dict[str, float] | None = None,
    protein_hit: bool = False,
    default_time_minutes: int | None = None,
    repetition_score: float = 0.0,
) -> float:
    """The hand-written ranking composite (see the module docstring)."""
    score = W_MATCH * cand.match_score
    if cand.uses_expiring:
        score += W_FRESH
    scores = {k.lower(): v for k, v in (cuisine_scores or {}).items()}
    score += W_CUISINE * scores.get((cand.cuisine or "").lower(), NEUTRAL)
    if cand.can_cook and protein_hit:
        score += W_PROTEIN
    if (
        cand.can_cook
        and default_time_minutes is not None
        and cand.cook_time is not None
        and cand.cook_time <= default_time_minutes
    ):
        score += W_TIME_FIT
    score -= W_REPETITION * repetition_score
    return round(score, 4)
