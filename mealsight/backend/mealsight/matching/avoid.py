"""Deterministic enforcement of avoid lists.

Until this module existed, avoid_ingredients and avoid_dishes reached the
single-request pipeline only as text in the reasoning prompt, so whether a
recipe containing an avoided ingredient got recommended depended on the
language model obeying an instruction. A nut-allergy request extracted as
avoid_ingredients=["nut"] (which the extraction model does, sometimes in
place of the dietary tag) therefore excluded nothing in code, and the old
exact-name match used by the multi-day planner could never connect "nut" to
"almonds" anyway.

This is the code-level check. Matching is whole-word ("egg" never matches
"eggplant", "nut" never matches "coconut"), and category words that name no
ingredient literally expand to their members.
"""

from __future__ import annotations

import re

_PUNCT = re.compile(r"[^\w\s]")
_PAREN = re.compile(r"\([^)]*(?:\)|$)")

ALLERGEN_GROUPS: dict[str, frozenset[str]] = {
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
            "pilchard",
            "squid",
            "octopus",
        }
    ),
    "nut": frozenset(
        {
            "almond",
            "walnut",
            "cashew",
            "pecan",
            "hazelnut",
            "pistachio",
            "macadamia",
            "peanut",
            "pine nut",
            "brazil nut",
            "chestnut",
        }
    ),
    "dairy": frozenset({"milk", "cheese", "butter", "cream", "yogurt", "yoghurt", "ghee"}),
    "cilantro": frozenset({"coriander"}),
    "coriander": frozenset({"cilantro"}),
}


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith(("shes", "ches", "xes", "zes", "oes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def words(phrase: str) -> list[str]:
    text = _PUNCT.sub("", _PAREN.sub(" ", phrase.lower()).replace("-", " "))
    return [_singular(w) for w in text.split() if w]


def _contains_run(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def ingredient_hits(avoid_terms: list[str], ingredient_names: list[str]) -> list[str]:
    """The avoid terms that any ingredient name contains, whole-word."""
    ingredient_words = [words(n) for n in ingredient_names]
    hits: list[str] = []
    for term in avoid_terms:
        term_words = words(term)
        if not term_words:
            continue
        group = ALLERGEN_GROUPS.get(" ".join(term_words), frozenset())
        needles = [term_words, *(words(member) for member in group)]
        if any(_contains_run(w, needle) for w in ingredient_words for needle in needles):
            hits.append(term)
    return hits


def dish_hits(avoid_dishes: list[str], recipe_name: str) -> list[str]:
    name_words = words(recipe_name)
    return [d for d in avoid_dishes if _contains_run(name_words, words(d))]


def implied_dietary_tags(avoid_terms: list[str]) -> list[str]:
    """Avoiding the whole nut group is the nut-free diet; apply the corpus
    tag as well so the search itself narrows, not just the later filter."""
    tags: list[str] = []
    for term in avoid_terms:
        if " ".join(words(term)) == "nut":
            tags.append("nut-free")
    return tags
