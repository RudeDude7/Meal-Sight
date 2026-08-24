"""Asymmetric specificity matching between two already-normalized
ingredient names.

The problem this solves: normalize_ingredient("chicken thighs") produces
"chicken thigh", not "chicken" — "thigh" isn't a container word or a prep
modifier, it's a real fact about which cut of chicken this is, and
stripping it would be wrong for plenty of other purposes (a recipe that
specifically wants a boneless chicken breast is not indifferent to
getting thighs instead). But for the matcher's purposes, "chicken thighs"
in the pantry against a recipe that just says "chicken" should count —
having a more specific cut than the recipe asked for is not a reason to
call an ingredient missing.

The rule this module implements:

    If the pantry item has every word the recipe requirement has, plus
    one or more extra words that are all recognized CUT/VARIETY
    modifiers (a specific cut of meat/fish, or a color/size variety) —
    the pantry item is MORE SPECIFIC than the requirement, and that's a
    FULL match. "chicken thighs" satisfies "chicken"; "salmon fillet"
    satisfies "salmon"; "red onion" satisfies "onion".

    If it's the other way around — the recipe requirement has extra
    words, all of them recognized cut/variety modifiers, that the pantry
    item lacks — the pantry item is LESS SPECIFIC than what the recipe
    actually wants, and that's a PARTIAL match, not a full one: the user
    has *an* onion, say, but the recipe wanted red onion specifically,
    and there's no way to know from a generic pantry entry whether that
    distinction matters for this particular dish.

    Everything else is NO match at this level (the ordinary matched/
    substitution/missing logic in mealsight.matching.matcher still gets
    a turn).

CUT_VARIETY_TERMS is deliberately a short, explicit list of words that
denote a cut, form, or variety of the *same* ingredient — never a word
that would turn one ingredient into a genuinely different one. That
second category (sweet potato is not a potato; cream cheese is not
cream; green onion is not onion; coconut milk is not milk) is exactly
what mealsight.matching.normalize.PROTECTED_TERMS exists to protect, and
this module treats that list as taking precedence: before ever calling
two normalized names a specificity match, it checks whether the exact
word combination in question is itself a protected multi-word
ingredient, and refuses to match if so, even if one of its words happens
to also appear in CUT_VARIETY_TERMS. In practice the two lists are kept
disjoint by construction (no word in CUT_VARIETY_TERMS is also a word
used to build a PROTECTED_TERMS phrase), so this check is a defensive
backstop against a future edit accidentally creating an overlap, not
something that fires in today's data.
"""

from __future__ import annotations

from typing import Literal

from mealsight.matching.normalize import PROTECTED_TERMS

SpecificityResult = Literal["full", "partial", "none"]

# Cuts, forms, and varieties of the same ingredient — never a word that
# creates a genuinely distinct ingredient. Deliberately excludes words
# already used inside PROTECTED_TERMS phrases (sweet, cream, coconut,
# green, spring, cocoa, brown, icing, etc.) — see the module docstring.
CUT_VARIETY_TERMS: frozenset[str] = frozenset(
    {
        # cuts of meat/poultry/fish
        "thigh", "breast", "wing", "drumstick", "leg", "tenderloin",
        "chop", "steak", "loin", "rib", "shank", "fillet", "cutlet",
        "shoulder", "brisket", "flank", "sirloin", "rump", "shin",
        # size/color varieties
        "red", "yellow", "white", "baby",
    }
)


def _forms_a_protected_term(words: frozenset[str]) -> bool:
    return any(set(term) == words for term in PROTECTED_TERMS)


def compare_specificity(recipe_normalized: str, pantry_normalized: str) -> SpecificityResult:
    """Compares one recipe requirement's normalized name against one
    pantry item's normalized name and reports whether the pantry item is
    a full (more-or-equally specific) match, a partial (less specific)
    match, or unrelated at this level entirely."""
    if not recipe_normalized or not pantry_normalized:
        return "none"

    recipe_words = frozenset(recipe_normalized.split())
    pantry_words = frozenset(pantry_normalized.split())

    if recipe_words == pantry_words:
        return "full"

    shared = recipe_words & pantry_words
    if not shared:
        return "none"

    extra_in_pantry = pantry_words - recipe_words
    extra_in_recipe = recipe_words - pantry_words

    if extra_in_pantry and not extra_in_recipe:
        if not all(word in CUT_VARIETY_TERMS for word in extra_in_pantry):
            return "none"
        if _forms_a_protected_term(pantry_words):
            return "none"
        return "full"

    if extra_in_recipe and not extra_in_pantry:
        if not all(word in CUT_VARIETY_TERMS for word in extra_in_recipe):
            return "none"
        if _forms_a_protected_term(recipe_words):
            return "none"
        return "partial"

    return "none"


def find_full_specificity_match(recipe_canonical: str, available_canonical: frozenset[str]) -> str | None:
    """Returns the first available pantry item (in sorted order, for
    determinism) that is a full specificity match for recipe_canonical,
    or None if there isn't one."""
    for candidate in sorted(available_canonical):
        if compare_specificity(recipe_canonical, candidate) == "full":
            return candidate
    return None


def find_partial_specificity_match(recipe_canonical: str, available_canonical: frozenset[str]) -> str | None:
    """Returns the first available pantry item (in sorted order, for
    determinism) that is a partial specificity match for
    recipe_canonical, or None if there isn't one."""
    for candidate in sorted(available_canonical):
        if compare_specificity(recipe_canonical, candidate) == "partial":
            return candidate
    return None
