"""The fixed dietary-restriction vocabulary analyze_voice_memo
normalizes every extracted restriction onto — the agent filters on
these as hard constraints, so a caller needs a closed, predictable set
of strings to match against, never whatever loose phrasing a voice
memo happened to use.

Deliberately hyphenated ("dairy-free", not "dairy_free"): this matches
the real ground truth in test_data/text/voice_scripts.json's own
expected_constraints exactly (dairy-free, gluten-free, peanut-free,
low-sodium, vegetarian all appear there in hyphenated form) — a real
project artifact takes precedence over an illustrative example, since
the whole point of a fixed vocabulary is for it to match what this
system's own eval data, and downstream consumers, actually expect.
"""

from __future__ import annotations

DIETARY_RESTRICTION_VOCABULARY: frozenset[str] = frozenset(
    {
        "vegetarian",
        "vegan",
        "pescatarian",
        "dairy-free",
        "gluten-free",
        "nut-free",
        "peanut-free",
        "shellfish-free",
        "soy-free",
        "egg-free",
        "low-sodium",
        "low-carb",
        "low-fat",
        "keto",
        "paleo",
        "halal",
        "kosher",
    }
)

# Loose phrasing (normalized: lowercased, spaces/underscores collapsed
# to hyphens) -> the one canonical vocabulary term it maps onto. Every
# vocabulary term also maps to itself, so a model that already produces
# clean output isn't penalized for it.
_DIETARY_RESTRICTION_SYNONYMS: dict[str, str] = {
    "vegetarian": "vegetarian",
    "veggie": "vegetarian",
    "vegan": "vegan",
    "plant-based": "vegan",
    "pescatarian": "pescatarian",
    "dairy-free": "dairy-free",
    "no-dairy": "dairy-free",
    "no-dairy-products": "dairy-free",
    "lactose-free": "dairy-free",
    "gluten-free": "gluten-free",
    "no-gluten": "gluten-free",
    "nut-free": "nut-free",
    "no-nuts": "nut-free",
    "tree-nut-free": "nut-free",
    "peanut-free": "peanut-free",
    "no-peanuts": "peanut-free",
    "shellfish-free": "shellfish-free",
    "no-shellfish": "shellfish-free",
    "soy-free": "soy-free",
    "no-soy": "soy-free",
    "egg-free": "egg-free",
    "no-eggs": "egg-free",
    "low-sodium": "low-sodium",
    "low-salt": "low-sodium",
    "low-carb": "low-carb",
    "low-carbohydrate": "low-carb",
    "low-fat": "low-fat",
    "keto": "keto",
    "ketogenic": "keto",
    "paleo": "paleo",
    "halal": "halal",
    "kosher": "kosher",
}


def normalize_dietary_restriction(raw: str) -> str | None:
    """Maps one loose, model-extracted dietary-restriction phrase onto
    DIETARY_RESTRICTION_VOCABULARY. Returns None — never a best guess —
    for a phrase that doesn't map onto anything recognized; the caller
    is responsible for not silently losing that information (see
    mealsight.perception.processor, which folds an unmapped phrase into
    additional_context rather than dropping it entirely)."""
    key = raw.strip().lower().replace("_", "-").replace(" ", "-")
    return _DIETARY_RESTRICTION_SYNONYMS.get(key)
