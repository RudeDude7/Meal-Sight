"""Everything that can change an eval result, hashed, so two scorecards can be
compared without guessing what differed.

Three groups, recorded separately on every scorecard:

  prompt_versions     every prompt sent to a model (vision, reasoning, extraction).
  component_versions  every lexicon, rule set or constant in code that shapes
                      results without being a prompt: the diet groups, the protein
                      lexicon, the cuisine families, the avoid/allergen groups, the
                      dietary-restriction backstop patterns, the matcher's
                      normalization rules and thresholds, the ranking weights.
  data_versions       the reference data the matcher and search read at run time:
                      the recipe corpus, the synonym and substitution tables, the
                      nutrition table. A re-seed changes these silently.

Each is a 12-hex-digit SHA-256 of a canonical JSON form, so a changed word in a
lexicon changes exactly one entry. The git diff hash is recorded too, but it
cannot say WHICH component moved; these can.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from typing import Any

from mealsight.db import get_recipe_db
from mealsight.perception.prompt import VISION_PERCEPTION_PROMPT, build_extraction_prompt


def digest(value: Any) -> str:
    """12 hex digits of the SHA-256 of a canonical JSON form (sets sorted, keys sorted).
    A plain string (a prompt) is hashed as-is, so prompt hashes stay comparable with every
    earlier scorecard."""
    if isinstance(value, str):
        return hashlib.sha256(value.encode()).hexdigest()[:12]

    def default(obj: Any) -> Any:
        if isinstance(obj, set | frozenset):
            return sorted(obj, key=repr)
        if hasattr(obj, "pattern"):  # compiled regex
            return obj.pattern
        if hasattr(obj, "__dataclass_fields__"):
            return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
        return repr(obj)

    blob = json.dumps(value, sort_keys=True, default=default, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def prompt_versions() -> dict[str, str]:
    reason = importlib.import_module("mealsight.agent.nodes.reason")  # package attr is the function
    return {
        "vision_perception_prompt": digest(VISION_PERCEPTION_PROMPT),
        "reasoning_prompt": digest(reason.SYSTEM_PROMPT),
        # The template with a fixed placeholder, so the hash covers the instructions, not a transcript.
        "extraction_prompt": digest(build_extraction_prompt("{{transcript}}")),
    }


def _module(name: str) -> Any:
    return importlib.import_module(name)


def component_versions() -> dict[str, str]:
    diet = _module("mealsight.matching.diet")
    protein = _module("mealsight.matching.protein")
    cuisine = _module("mealsight.matching.cuisine")
    avoid = _module("mealsight.matching.avoid")
    normalize = _module("mealsight.matching.normalize")
    specificity = _module("mealsight.matching.specificity")
    backstop = _module("mealsight.perception.restrictions")
    dietary = _module("mealsight.perception.dietary")
    match_rank = _module("mealsight.agent.nodes.match_rank")
    settings = _module("mealsight.config.settings").settings
    return {
        "diet_groups": digest(
            {
                "tag_backed": diet.TAG_BACKED,
                "ingredient_enforced": diet.INGREDIENT_ENFORCED,
                "unenforced": diet.UNENFORCED,
            }
        ),
        "dietary_vocabulary": digest(
            {
                "vocabulary": dietary.DIETARY_RESTRICTION_VOCABULARY,
                "synonyms": dietary._DIETARY_RESTRICTION_SYNONYMS,
            }
        ),
        "protein_lexicon": digest({"groups": protein.PROTEIN_GROUPS, "flavouring": protein.FLAVOURING_WORDS}),
        "cuisine_families": digest(cuisine._FAMILIES),
        "avoid_groups": digest(avoid.ALLERGEN_GROUPS),
        "restriction_backstop_patterns": digest(
            {
                "patterns": backstop._PATTERNS,
                "self_correction": backstop._SELF_CORRECTION,
                "negated": backstop._NEGATED,
                "possession": backstop._POSSESSION,
            }
        ),
        "matcher_normalization": digest(
            {
                "container": normalize._CONTAINER_WORDS,
                "prep": normalize._PREP_MODIFIERS,
                "protected": normalize.PROTECTED_TERMS,
                "uncountable": normalize._UNCOUNTABLE_EXCEPTIONS,
                "irregular": normalize._IRREGULAR_SINGULARS,
                "cut_variety": specificity.CUT_VARIETY_TERMS,
            }
        ),
        "matcher_thresholds": digest(
            {
                "min_ingredient_match": settings.min_ingredient_match,
                "substitution_match_weight": settings.substitution_match_weight,
                "critical_missing_penalty": settings.critical_missing_penalty,
                "expired_grace_days": settings.expired_grace_days,
                "expiring_soon_days": settings.expiring_soon_days,
            }
        ),
        "ranking_weights": digest(
            {
                name: getattr(match_rank, name)
                for name in dir(match_rank)
                if name.endswith("_WEIGHT") or name.endswith("_PENALTY") or name == "NEUTRAL_CUISINE_SCORE"
            }
        ),
    }


async def data_versions() -> dict[str, str]:
    """Content hashes of the reference tables read at run time."""
    db = get_recipe_db()
    queries = {
        "recipe_corpus": "SELECT id, name, cuisine, meal_type, cook_time_minutes, servings_base, "
        "dietary_tags, ingredients FROM recipes ORDER BY id",
        "ingredient_synonyms": "SELECT canonical_name, synonym FROM ingredient_synonyms "
        "ORDER BY canonical_name, synonym",
        "substitutions": "SELECT original_ingredient, substitute, ratio, flavor_impact FROM substitutions "
        "ORDER BY original_ingredient, substitute",
        "nutrition_reference": "SELECT * FROM nutrition_reference ORDER BY ingredient",
    }
    out: dict[str, str] = {}
    for name, query in queries.items():
        rows = await db.fetch_all(query)
        out[name] = digest([list(row) for row in rows])
    return out
