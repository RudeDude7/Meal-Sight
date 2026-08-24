"""Ingredient name normalization: turns messy, free-text ingredient names
("Freshly chopped parsley", "a can of chopped tomatoes", "Sweet Potatoes")
into a stable, comparable form ("parsley", "chopped tomato" -> "tomato",
"sweet potato"), so the matcher can compare a recipe's ingredient names
against a pantry's ingredient names as plain strings.

Pure, deterministic, no network or database access — every function here
takes a string in and returns a string out.
"""

from __future__ import annotations

import re

# Packaging/container words: describe how the ingredient was packaged, not
# what it is. "a" and "of" are included because they show up constantly in
# phrases like "a can of chopped tomatoes" and carry no identity either.
_CONTAINER_WORDS = frozenset(
    {
        "carton", "jar", "jarred", "bottle", "bottled", "container", "tub",
        "packet", "package", "packaged", "bag", "bagged", "box", "boxed",
        "can", "canned", "of", "a",
    }
)

# Preparation modifiers named in the spec: how an ingredient was prepped,
# not what it is.
_SPEC_PREP_MODIFIERS = frozenset(
    {
        "chopped", "diced", "minced", "sliced", "fresh", "frozen", "cooked",
        "raw", "large", "small", "boneless", "skinless",
    }
)

# Additional modifiers actually observed in the seeded recipes.ingredients
# data during the phase 2 data audit (e.g. "Freshly chopped parsley",
# "Cubed Feta cheese", "shredded Monterey Jack cheese", "free-range eggs,
# beaten", "chilled butter") — same "describes prep, not identity" category
# as the ones above, just not enumerated in the original spec list.
_EXTRA_PREP_MODIFIERS = frozenset(
    {
        "freshly", "cubed", "grated", "crushed", "ground", "peeled",
        "shredded", "beaten", "chilled", "softened", "melted", "ripe",
        "whole", "plain", "dried", "cold", "warm", "hot", "finely", "roughly",
    }
)

_PREP_MODIFIERS = _SPEC_PREP_MODIFIERS | _EXTRA_PREP_MODIFIERS

# Multi-word ingredients that must never be collapsed down to one of their
# own component words, since the result would be a genuinely different
# ingredient (a sweet potato is not a potato; cream cheese is not cream).
# Each entry is stored as a tuple of its own already-singularized words, so
# it can be matched against a word list that's already been through
# _singularize_word. Sourced from
# backend/tests/test_seed/test_synonyms_distinctness.py's DISTINCT_PAIRS
# plus a few more of the same shape found in the real seeded ingredient
# data (rice flour / corn flour, both genuinely gluten-free and not to be
# confused with plain "flour").
PROTECTED_TERMS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("sweet", "potato"),
        ("cream", "cheese"),
        ("sour", "cream"),
        ("coconut", "milk"),
        ("coconut", "cream"),
        ("peanut", "butter"),
        ("cocoa", "butter"),
        ("cocoa", "powder"),
        ("green", "onion"),
        ("spring", "onion"),
        ("chicken", "stock"),
        ("beef", "stock"),
        ("vegetable", "stock"),
        ("brown", "sugar"),
        ("icing", "sugar"),
        ("rice", "flour"),
        ("corn", "flour"),
        ("almond", "flour"),
        ("rice", "noodle"),
        ("cream", "cheese", "frosting"),
        ("nut", "butter"),
        ("tomato", "paste"),
        ("tomato", "puree"),
        ("olive", "oil"),
        ("sesame", "oil"),
        ("soy", "sauce"),
        ("fish", "sauce"),
        ("oyster", "sauce"),
        ("hot", "sauce"),
    }
)

_NON_WORD_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")

# Words a naive "strip trailing s" rule would mangle — already singular,
# not plurals of some shorter word.
_UNCOUNTABLE_EXCEPTIONS = frozenset(
    {
        "hummus", "couscous", "asparagus", "molasses", "citrus", "chives",
        "greens", "grits", "oats", "peas",
    }
)

_IRREGULAR_SINGULARS = {
    "leaves": "leaf",
    "loaves": "loaf",
    "halves": "half",
}


def _singularize_word(word: str) -> str:
    if word in _UNCOUNTABLE_EXCEPTIONS:
        return word
    if word in _IRREGULAR_SINGULARS:
        return _IRREGULAR_SINGULARS[word]
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith(("ches", "shes", "xes", "ses")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _protect_multi_word_terms(words: list[str]) -> list[str]:
    """Glues any contiguous run of words matching a PROTECTED_TERMS tuple
    into a single underscore-joined token, so a later pass that strips
    container/prep words word-by-word can't reach inside it and break it
    apart. Longer terms are tried first so a 3-word protected phrase isn't
    pre-empted by a 2-word one that happens to be a prefix of it."""
    protected_sorted = sorted(PROTECTED_TERMS, key=len, reverse=True)
    result: list[str] = []
    i = 0
    while i < len(words):
        matched_term: tuple[str, ...] | None = None
        for term in protected_sorted:
            end = i + len(term)
            if end <= len(words) and tuple(words[i:end]) == term:
                matched_term = term
                break
        if matched_term is not None:
            result.append("_".join(matched_term))
            i += len(matched_term)
        else:
            result.append(words[i])
            i += 1
    return result


def normalize_ingredient(name: str) -> str:
    """Normalizes a free-text ingredient name into a stable, comparable
    form: lowercased, punctuation stripped, container/packaging words and
    preparation modifiers removed, plurals singularized — while never
    collapsing a protected multi-word ingredient (see PROTECTED_TERMS)
    down to one of its own component words.
    """
    if not name:
        return ""

    lowered = name.lower().replace("-", " ")
    cleaned = _NON_WORD_RE.sub(" ", lowered)
    words = [w for w in _WHITESPACE_RE.split(cleaned) if w]

    singularized = [_singularize_word(w) for w in words]
    protected = _protect_multi_word_terms(singularized)

    kept = [w for w in protected if w not in _CONTAINER_WORDS and w not in _PREP_MODIFIERS]

    normalized = " ".join(w.replace("_", " ") for w in kept)
    return _WHITESPACE_RE.sub(" ", normalized).strip()
