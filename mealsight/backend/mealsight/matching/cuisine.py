"""One place that decides whether two cuisine names mean the same cuisine.

The corpus labels recipes with TheMealDB's "area" names, which mix two
conventions: demonyms ("British", "Italian", "Jamaican") and country names
("India", "France", "Netherlands", "United States"). Users, and the
extraction model, say either. Search matched by exact string, so "Indian"
and "French" matched nothing, and the reasoning layer then told the user
"None of the candidates is Indian cuisine" while Chicken Handi (cuisine
"India") was cookable. Every cuisine comparison goes through here instead.

Each family below is one cuisine: its corpus label first, then every other
name for it (the country, the demonym, common variants). Matching is
case-insensitive and either direction works. Anything not in a family is
compared as a normalized string, so a label added to the corpus later still
matches itself; tests assert the seeded corpus's labels are all covered by a
family, so an unmapped new label fails loudly rather than silently
becoming unreachable by its demonym.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

# (corpus label, *other names). The first entry is the label stored in the corpus.
_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("British", "britain", "united kingdom", "uk", "english", "scottish", "welsh"),
    ("United States", "american", "usa", "us", "u s", "united states of america", "america"),
    ("France", "french"),
    ("Italian", "italy"),
    ("Canadian", "canada"),
    ("Chinese", "china"),
    ("India", "indian"),
    ("Greek", "greece"),
    ("Jamaican", "jamaica"),
    ("Polish", "poland"),
    ("Tunisian", "tunisia"),
    ("Egyptian", "egypt"),
    ("Japanese", "japan"),
    ("Mexican", "mexico"),
    ("Moroccan", "morocco"),
    ("Irish", "ireland"),
    ("Netherlands", "dutch", "holland", "the netherlands"),
    ("Spanish", "spain"),
    ("Thai", "thailand"),
    ("Kenyan", "kenya"),
    ("Turkish", "turkey"),
    ("Vietnamese", "vietnam"),
    ("Malaysian", "malaysia"),
    ("Russian", "russia"),
)

NEUTRAL_SCORE = 0.5
_NON_WORD = re.compile(r"[^a-z\s]")


def _norm(name: str) -> str:
    return " ".join(_NON_WORD.sub(" ", name.lower()).split())


_KEY_BY_NAME: dict[str, str] = {}
for _family in _FAMILIES:
    _label_key = _norm(_family[0])
    for _name in _family:
        _KEY_BY_NAME[_norm(_name)] = _label_key


def cuisine_key(name: str) -> str:
    """A canonical key: two names with the same key are the same cuisine."""
    normalized = _norm(name)
    return _KEY_BY_NAME.get(normalized, normalized)


def cuisines_match(asked: str | None, label: str | None) -> bool:
    """Whether a requested cuisine and a recipe's label are the same cuisine."""
    if not asked or not label:
        return False
    return cuisine_key(asked) == cuisine_key(label)


def corpus_labels_for(asked: str, labels: Iterable[str]) -> list[str]:
    """The labels (as stored) that satisfy the requested cuisine."""
    return [label for label in labels if cuisines_match(asked, label)]


def known_labels() -> list[str]:
    return [family[0] for family in _FAMILIES]


def canonical_cuisine_label(name: str) -> str:
    """The one spelling under which a cuisine is stored and compared: the corpus label for a known
    cuisine ("italian", "Italian" and "ITALY" are all "Italian"; "Indian" is "India"), else the name with
    its words capitalized. Used where preference scores are WRITTEN and READ, so the key never depends on
    how a meal happened to be logged."""
    key = cuisine_key(name)
    for family in _FAMILIES:
        if cuisine_key(family[0]) == key:
            return family[0]
    return name.strip().title()


def lookup_cuisine_score(
    scores: Mapping[str, Any], cuisine: str | None, default: float = NEUTRAL_SCORE
) -> float:
    """The preference score for `cuisine` from a {cuisine: score} mapping, matched by cuisine family
    rather than by exact key, so a mapping built with any capitalization or name form still resolves."""
    if not cuisine:
        return default
    wanted = cuisine_key(cuisine)
    for key, value in scores.items():
        if cuisine_key(str(key)) == wanted and isinstance(value, int | float):
            return float(value)
    return default


def collapse_cuisine_scores(
    scores: Mapping[str, float], data_points: Mapping[str, int]
) -> tuple[dict[str, float], dict[str, int]]:
    """Re-keys stored scores by canonical label. Rows written before keys were canonicalized can hold the
    same cuisine under two spellings; they merge here as a mean weighted by data_points, so no stored data
    needs a migration to be read correctly."""
    acc: dict[str, tuple[float, int, int]] = {}  # label -> (weighted score sum, weight sum, data points)
    for key, score in scores.items():
        label = canonical_cuisine_label(key)
        points = int(data_points.get(key, 0))
        weight = max(points, 1)
        total, weights, seen = acc.get(label, (0.0, 0, 0))
        acc[label] = (total + float(score) * weight, weights + weight, seen + points)
    merged = {label: total / weights for label, (total, weights, _) in acc.items()}
    return merged, {label: seen for label, (_, _, seen) in acc.items()}
