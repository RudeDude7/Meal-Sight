"""The core ingredient matching algorithm: given a recipe's required
ingredients and what's actually available (a pantry), decides which
ingredients are matched, substitutable, or missing, and scores the
result.

Pure and deterministic — no network calls, no LLM calls. The only I/O in
this module is the one-time, cached load of the synonyms and
substitutions reference tables (see mealsight.matching.synonyms and
mealsight.matching.substitutions); match_recipe itself takes plain data
in and returns a plain MatchResult out, so it's fully unit-testable
without a database.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.matching.models import (
    Importance,
    MatchedItem,
    MatchResult,
    MissingItem,
    PartialMatchItem,
    SubstitutableItem,
)
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.specificity import find_full_specificity_match, find_partial_specificity_match
from mealsight.matching.substitutions import SubstitutionOption, load_substitution_map
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.seed.recipe_parsing import derive_dietary_tags

# Lower rank sorts first — a "minimal" flavor-impact substitute is
# preferred over "noticeable", which is preferred over "significant".
FLAVOR_IMPACT_RANK: dict[str, int] = {"minimal": 0, "noticeable": 1, "significant": 2}
UNKNOWN_FLAVOR_IMPACT_RANK = 3


@dataclass(frozen=True)
class RecipeIngredientInput:
    name: str
    importance: Importance


def parse_recipe_ingredients(ingredients_json: str) -> list[RecipeIngredientInput]:
    """Parses the recipes.ingredients JSON column (a list of
    {"name", "quantity", "unit", "importance", "raw_measure"} objects,
    per mealsight/db/schema/recipes.sql) into the name/importance pairs
    the matcher actually needs."""
    raw_items: list[dict[str, Any]] = json.loads(ingredients_json)
    return [RecipeIngredientInput(name=item["name"], importance=item["importance"]) for item in raw_items]


def substitute_satisfies_dietary_restrictions(
    substitute_name: str, dietary_restrictions: Sequence[str]
) -> bool:
    """Whether a candidate substitute is safe to offer under every
    requested dietary restriction. Reuses the same rule-based, tested
    derive_dietary_tags logic the seed pipeline uses to tag whole recipes
    (mealsight.seed.recipe_parsing) rather than duplicating its term
    lists here — a substitute that itself contains dairy fails a
    dairy_free restriction the same way a whole recipe containing dairy
    would fail to earn the dairy_free tag."""
    if not dietary_restrictions:
        return True
    substitute_tags = set(derive_dietary_tags([substitute_name]))
    return all(restriction in substitute_tags for restriction in dietary_restrictions)


def _best_eligible_substitute(
    options: Sequence[SubstitutionOption],
    available_canonical: frozenset[str],
    synonym_map: Mapping[str, str],
    dietary_restrictions: Sequence[str],
) -> SubstitutionOption | None:
    eligible = [
        option
        for option in options
        if resolve_canonical(normalize_ingredient(option.substitute), synonym_map) in available_canonical
        and substitute_satisfies_dietary_restrictions(option.substitute, dietary_restrictions)
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda option: FLAVOR_IMPACT_RANK.get(option.flavor_impact, UNKNOWN_FLAVOR_IMPACT_RANK),
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _build_summary(
    can_cook: bool,
    score: float,
    matched: list[MatchedItem],
    substitutable: list[SubstitutableItem],
    partial: list[PartialMatchItem],
    missing: list[MissingItem],
    critical_missing: list[str],
) -> str:
    parts: list[str] = [f"Match score {score:.2f}", "can cook" if can_cook else "cannot cook"]

    if substitutable:
        subs = "; ".join(f"{item.substitute} for {item.original}" for item in substitutable)
        parts.append(f"{len(substitutable)} substitution(s) applied ({subs})")

    if partial:
        notes = "; ".join(f"{item.pantry_match} for {item.name}" for item in partial)
        parts.append(f"{len(partial)} less-specific match(es) ({notes})")

    if critical_missing:
        parts.append(f"missing critical: {', '.join(critical_missing)}")

    non_critical_missing = [item for item in missing if item.importance != "critical"]
    if non_critical_missing:
        by_importance: dict[str, list[str]] = {"important": [], "optional": []}
        for item in non_critical_missing:
            by_importance.setdefault(item.importance, []).append(item.name)
        for importance, names in by_importance.items():
            if names:
                parts.append(f"missing {importance}: {', '.join(names)}")

    if not matched and not substitutable and not missing:
        parts.append("recipe has no ingredients")

    return ". ".join(parts) + "."


def match_recipe(
    recipe_ingredients: Sequence[RecipeIngredientInput],
    pantry_items: Sequence[str],
    substitution_map: Mapping[str, Sequence[SubstitutionOption]],
    synonym_map: Mapping[str, str],
    dietary_restrictions: Sequence[str] | None = None,
) -> MatchResult:
    """Matches one recipe's required ingredients against one pantry's
    available ingredients, returning a scored, typed result.

    dietary_restrictions gates which substitutes are eligible (section 3
    of the matcher spec) — it does not filter matched_items, since an
    ingredient the pantry already has is the user's own to decide about,
    not something this function second-guesses.
    """
    dietary_restrictions = dietary_restrictions or ()
    restrictions_tuple = tuple(dietary_restrictions)

    available_canonical = frozenset(
        resolve_canonical(normalize_ingredient(item), synonym_map) for item in pantry_items
    )

    matched_items: list[MatchedItem] = []
    substitutable_items: list[SubstitutableItem] = []
    partial_matches: list[PartialMatchItem] = []
    missing_items: list[MissingItem] = []
    critical_missing: list[str] = []

    for ingredient in recipe_ingredients:
        canonical = resolve_canonical(normalize_ingredient(ingredient.name), synonym_map)

        if canonical in available_canonical:
            matched_items.append(MatchedItem(name=canonical, importance=ingredient.importance))
            continue

        # A pantry item that's a more specific cut/variety of the same
        # ingredient (e.g. "chicken thighs" for a recipe that just wants
        # "chicken") satisfies the requirement fully — see
        # mealsight.matching.specificity for the exact rule.
        full_specificity_match = find_full_specificity_match(canonical, available_canonical)
        if full_specificity_match is not None:
            matched_items.append(MatchedItem(name=canonical, importance=ingredient.importance))
            continue

        options = substitution_map.get(canonical, ())
        best = _best_eligible_substitute(options, available_canonical, synonym_map, restrictions_tuple)
        if best is not None:
            substitutable_items.append(
                SubstitutableItem(
                    original=canonical,
                    substitute=best.substitute,
                    ratio=best.ratio,
                    flavor_impact=best.flavor_impact,  # type: ignore[arg-type]
                    importance=ingredient.importance,
                )
            )
            continue

        # A pantry item that's only a generic form of what the recipe
        # specifically wants (e.g. pantry has plain "chicken" but the
        # recipe wants "chicken thighs") is a partial match: usable, but
        # possibly not the right cut/variety.
        partial_pantry_match = find_partial_specificity_match(canonical, available_canonical)
        if partial_pantry_match is not None:
            partial_matches.append(
                PartialMatchItem(
                    name=canonical,
                    pantry_match=partial_pantry_match,
                    importance=ingredient.importance,
                    note=(
                        f"pantry has {partial_pantry_match!r}, a less specific form of "
                        f"{canonical!r} — may not be the right cut or variety"
                    ),
                )
            )
            continue

        missing_items.append(MissingItem(name=canonical, importance=ingredient.importance))
        if ingredient.importance == "critical":
            critical_missing.append(canonical)

    total_required = len(recipe_ingredients)
    if total_required == 0:
        score = 0.0
    else:
        substitution_weight = (
            len(substitutable_items) + len(partial_matches)
        ) * settings.substitution_match_weight
        matched_weight = float(len(matched_items)) + substitution_weight
        base = matched_weight / total_required
        penalty = settings.critical_missing_penalty * len(critical_missing)
        score = _clamp(base - penalty, 0.0, 1.0)

    can_cook = score >= settings.min_ingredient_match and not critical_missing

    summary = _build_summary(
        can_cook, score, matched_items, substitutable_items, partial_matches, missing_items, critical_missing
    )

    return MatchResult(
        match_score=round(score, 4),
        can_cook=can_cook,
        matched_items=matched_items,
        substitutable_items=substitutable_items,
        partial_matches=partial_matches,
        missing_items=missing_items,
        critical_missing=critical_missing,
        summary=summary,
    )


@dataclass(frozen=True)
class MatchContext:
    """The two cached reference maps match_recipe needs, bundled together
    so callers only have to load them once."""

    synonym_map: dict[str, str]
    substitution_map: dict[str, list[SubstitutionOption]]


async def build_match_context(db: Database) -> MatchContext:
    synonym_map = await load_synonym_map(db)
    substitution_map = await load_substitution_map(db)
    return MatchContext(synonym_map=synonym_map, substitution_map=substitution_map)


async def match_recipe_by_id(
    db: Database,
    recipe_id: str,
    pantry_items: Sequence[str],
    dietary_restrictions: Sequence[str] | None = None,
    context: MatchContext | None = None,
) -> MatchResult:
    """Convenience wrapper: fetches one recipe by id, parses its
    ingredients, and matches it against pantry_items. Raises ValueError if
    no recipe with that id exists."""
    row = await db.fetch_one("SELECT ingredients FROM recipes WHERE id = ?", (recipe_id,))
    if row is None:
        raise ValueError(f"No recipe found with id {recipe_id!r}")

    recipe_ingredients = parse_recipe_ingredients(row["ingredients"])
    context = context or await build_match_context(db)
    return match_recipe(
        recipe_ingredients,
        pantry_items,
        context.substitution_map,
        context.synonym_map,
        dietary_restrictions,
    )
