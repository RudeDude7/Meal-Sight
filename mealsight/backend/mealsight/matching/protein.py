"""One protein vocabulary, shared by ranking (match_rank's protein term)
and by the reasoning facts (protein_met), so the two can never disagree
about what "fish" or "seafood" means.

A stated preference such as "seafood or fish" names a category, not an
ingredient. Each category expands to its members, a preference is split
on "or"/"and"/commas into alternatives, and a recipe satisfies it when one
of its ingredient names contains a member as a whole word (never a
substring: "egg" is not in "eggplant").

Ingredients that only flavour a dish (stock, sauce, paste, powder, oil...)
do not count as the protein itself: a vegetable soup made with a chicken
stock cube is not a chicken dish, and fish sauce is not fish.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from mealsight.matching.normalize import normalize_ingredient

SHELLFISH = frozenset(
    {"shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster", "scallop", "crayfish", "langoustine"}
)
FISH = frozenset(
    {
        "fish",
        "salmon",
        "tuna",
        "cod",
        "haddock",
        "mackerel",
        "trout",
        "sardine",
        "anchovy",
        "halibut",
        "tilapia",
        "herring",
        "snapper",
        "sole",
        "pollock",
        "swordfish",
        "monkfish",
        "hake",
        "bass",
        "whitebait",
        "kipper",
        "carp",
        "catfish",
    }
)
POULTRY = frozenset({"chicken", "turkey", "duck", "goose", "quail", "poultry"})
RED_MEAT = frozenset(
    {
        "beef",
        "pork",
        "lamb",
        "veal",
        "mutton",
        "venison",
        "ham",
        "bacon",
        "sausage",
        "chorizo",
        "salami",
        "steak",
        "brisket",
        "mince",
        "meatball",
    }
)

# Category word -> every member it stands for. "meat" deliberately includes
# poultry: someone asking for "meat" would accept chicken. "red meat" does not.
PROTEIN_GROUPS: dict[str, frozenset[str]] = {
    "shellfish": SHELLFISH,
    "fish": FISH,
    "seafood": SHELLFISH | FISH | {"squid", "octopus", "calamari", "seafood"},
    "poultry": POULTRY,
    "red meat": RED_MEAT,
    "meat": RED_MEAT | POULTRY | {"meat"},
    # Two names for one animal.
    "shrimp": frozenset({"shrimp", "prawn"}),
    "prawn": frozenset({"shrimp", "prawn"}),
}

# An ingredient whose name contains one of these flavours a dish; it is not the protein.
FLAVOURING_WORDS = frozenset(
    {
        "stock",
        "broth",
        "bouillon",
        "cube",
        "sauce",
        "paste",
        "powder",
        "seasoning",
        "oil",
        "gravy",
        "essence",
        "extract",
        "flavouring",
        "flavoring",
    }
)

_SPLIT_RE = re.compile(r"\s*(?:,|/|&|\bor\b|\band/or\b|\band\b)\s*")


def is_general_protein_request(preference: str) -> bool:
    """ "high-protein" style asks are about nutrition, not a specific food."""
    return "protein" in preference.lower()


def protein_members(preference: str) -> frozenset[str]:
    """Every ingredient word that would satisfy the preference."""
    members: set[str] = set()
    for part in _SPLIT_RE.split(preference.lower()):
        normalized = normalize_ingredient(part.strip())
        if not normalized:
            continue
        members |= PROTEIN_GROUPS.get(normalized, frozenset({normalized}))
    return frozenset(members)


def ingredient_is_protein(ingredient_name: str, members: Iterable[str]) -> bool:
    """Whole-word membership, ignoring flavouring-only ingredients."""
    words = normalize_ingredient(ingredient_name).split()
    if not words or FLAVOURING_WORDS & set(words):
        return False
    text = " " + " ".join(words) + " "
    return any(f" {member} " in text for member in members)


def names_include_protein(ingredient_names: Iterable[str], preference: str) -> bool:
    members = protein_members(preference)
    return bool(members) and any(ingredient_is_protein(n, members) for n in ingredient_names)
