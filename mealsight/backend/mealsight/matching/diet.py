"""How every dietary restriction in the extraction vocabulary is actually
enforced. This is the one place that says so.

The extraction vocabulary (mealsight.perception.dietary) has 17 restrictions.
Only five exist as tags in the recipe corpus. The old code sent all 17 to
search as hard tag filters, so the other twelve matched zero recipes and a
request carrying one (a stated peanut allergy, say) produced a refusal instead
of protection. Each restriction now belongs to exactly one group:

  TAG_BACKED          the corpus has a real tag; search filters on it.
  INGREDIENT_ENFORCED checked against each candidate's ingredient list with
                      the whole-word matcher in mealsight.matching.avoid and
                      the term sets in mealsight.matching.protein. Some are
                      PARTIAL: the check is real but is not the whole of the
                      restriction (halal, kosher), and says so.
  UNENFORCED          the system cannot check this. It is stated to the user
                      as not enforced, never silently ignored. This includes
                      all the nutritional restrictions: measured against the
                      real corpus, calculate_nutrition is not reliable enough
                      to filter on (see the note on UNENFORCED below).

The module asserts at import that the four groups together are exactly the
extraction vocabulary, with no overlap. Add a restriction to the vocabulary
without classifying it here and the application fails to start, so a new
restriction can never quietly become a dead tag filter again.
"""

from __future__ import annotations

from dataclasses import dataclass

from mealsight.matching.avoid import ALLERGEN_GROUPS, ingredient_hits
from mealsight.matching.protein import FISH, POULTRY, RED_MEAT, SHELLFISH
from mealsight.perception.dietary import DIETARY_RESTRICTION_VOCABULARY

# --- group 1: tags the corpus really carries (mealsight.seed.recipe_parsing.derive_dietary_tags) ---
TAG_BACKED: frozenset[str] = frozenset({"vegetarian", "vegan", "dairy-free", "gluten-free", "nut-free"})


# --- group 2: enforced against ingredient lists ---
@dataclass(frozen=True)
class IngredientRule:
    exclude: frozenset[str]
    # An ingredient containing one of these words is not matched ("red wine vinegar" is not alcohol).
    exempt_words: frozenset[str] = frozenset()
    # Kosher-style: a recipe containing a member of BOTH sets violates the rule.
    mixes: tuple[frozenset[str], frozenset[str]] | None = None
    # What the check does NOT cover. Empty when the ingredient check is the whole restriction.
    limitation: str = ""


_PORK = frozenset(
    {
        "pork",
        "bacon",
        "ham",
        "lard",
        "pancetta",
        "prosciutto",
        "chorizo",
        "gammon",
        "sausage",
        "salami",
        "pepperoni",
        "guanciale",
    }
)
_ALCOHOL = frozenset(
    {
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
        "gin",
        "bourbon",
        "cognac",
        "champagne",
        "prosecco",
        "stout",
        "ale",
        "lager",
        "amaretto",
        "kirsch",
        "marsala",
        "mirin",
        "calvados",
        "tequila",
    }
)
_MEAT = RED_MEAT | POULTRY | {"meat", "lard", "gelatin", "suet", "tallow", "prosciutto", "pancetta", "gammon"}

INGREDIENT_ENFORCED: dict[str, IngredientRule] = {
    "peanut-free": IngredientRule(frozenset({"peanut", "groundnut"})),
    "shellfish-free": IngredientRule(SHELLFISH | {"shellfish", "scampi"}),
    "soy-free": IngredientRule(frozenset({"soy", "soya", "tofu", "tempeh", "edamame", "miso", "tamari"})),
    "egg-free": IngredientRule(frozenset({"egg", "mayonnaise", "mayo", "meringue", "albumen"})),
    # Fish and shellfish are allowed; meat and poultry (including stock, lard, gelatin) are not.
    "pescatarian": IngredientRule(_MEAT),
    "halal": IngredientRule(
        _PORK | _ALCOHOL,
        exempt_words=frozenset({"vinegar"}),
        limitation="Pork and alcohol ingredients are excluded; halal slaughter and certification cannot "
        "be verified from a recipe.",
    ),
    "kosher": IngredientRule(
        _PORK | SHELLFISH | {"shellfish"},
        mixes=(RED_MEAT | POULTRY, ALLERGEN_GROUPS["dairy"]),
        limitation="Pork, shellfish and recipes mixing meat with dairy are excluded; kosher slaughter, "
        "supervision and certification cannot be verified from a recipe.",
    ),
}

# --- group 3: not enforced, with the reason that is shown to the user ---
#
# Why the nutritional restrictions are here and not filtered on calculate_nutrition. Measured over
# all 250 recipes (2026-11-06): ingredient coverage exceeds 80% for 189 of them, but the figures are
# built from rough unit-to-gram conversions (a bare "1 onion" is 100 g, volumes are at water density)
# and are not trustworthy even where coverage is high: Kumpir, a baked-potato dish, comes out at 13 g
# carbs per serving and gets the `low_carb` tag, Creamy Tomato Soup at 241 g; sodium runs from 6 mg to
# 33,192 mg per serving because unquantified salt is simply missing; median fat is 60 g per serving.
# Filtering on that would return confidently wrong recipes. Declining is the honest behaviour, and
# the request is answered with an explicit "not enforced" instead of a refusal or a silent pass.
_NUTRITION_REASON = (
    "Nutrition figures are estimated from rough ingredient quantities and are not reliable enough to "
    "filter recipes on"
)
UNENFORCED: dict[str, str] = {
    "low-carb": f"{_NUTRITION_REASON} (a baked-potato dish was estimated at 13 g carbs per serving).",
    "keto": f"{_NUTRITION_REASON}, and keto also depends on fat ratio, which cannot be checked.",
    "low-sodium": "Sodium cannot be estimated reliably: unquantified salt and seasoning are missing "
    "from the totals, and no threshold is defined.",
    "low-fat": "Fat per serving cannot be estimated reliably from rough ingredient quantities, and no "
    "low-fat threshold is defined.",
    "paleo": "Paleo has no single agreed definition, so it cannot be checked mechanically.",
}

_ALL = [TAG_BACKED, frozenset(INGREDIENT_ENFORCED), frozenset(UNENFORCED)]
assert sum(len(g) for g in _ALL) == len(frozenset().union(*_ALL)), "a restriction is in two groups"
assert frozenset().union(*_ALL) == DIETARY_RESTRICTION_VOCABULARY, (
    "mealsight.matching.diet must classify every restriction in the extraction vocabulary exactly once; "
    f"unclassified: {sorted(DIETARY_RESTRICTION_VOCABULARY - frozenset().union(*_ALL))}, "
    f"not in the vocabulary: {sorted(frozenset().union(*_ALL) - DIETARY_RESTRICTION_VOCABULARY)}"
)

PARTIAL = frozenset(name for name, rule in INGREDIENT_ENFORCED.items() if rule.limitation)


@dataclass(frozen=True)
class SplitRestrictions:
    tag_filters: list[str]  # corpus-tag spelling (underscores), safe to send to search
    ingredient: list[str]
    unenforced: list[str]


def split_restrictions(restrictions: list[str]) -> SplitRestrictions:
    tag, ingredient, unenforced = [], [], []
    for restriction in restrictions:
        if restriction in TAG_BACKED:
            tag.append(restriction.replace("-", "_"))
        elif restriction in INGREDIENT_ENFORCED:
            ingredient.append(restriction)
        else:  # UNENFORCED, or anything not classified: never a tag filter, always disclosed
            unenforced.append(restriction)
    return SplitRestrictions(tag, ingredient, unenforced)


def ingredient_violations(restriction: str, ingredient_names: list[str]) -> list[str]:
    """Human-readable reasons the ingredient list breaks the restriction ('peanut (peanut butter)')."""
    rule = INGREDIENT_ENFORCED.get(restriction)
    if rule is None:
        return []
    names = [
        n for n in ingredient_names if not (rule.exempt_words & set(n.lower().replace("-", " ").split()))
    ]
    found: list[str] = []
    for name in names:
        for term in ingredient_hits(sorted(rule.exclude), [name]):
            found.append(f"{term} ({name})")
    if rule.mixes:
        meat = [n for n in names if ingredient_hits(sorted(rule.mixes[0]), [n])]
        dairy = [n for n in names if ingredient_hits(sorted(rule.mixes[1]), [n])]
        if meat and dairy:
            found.append(f"meat and dairy together ({meat[0]} with {dairy[0]})")
    return found


def violated_ingredient_restrictions(restrictions: list[str], ingredient_names: list[str]) -> list[str]:
    out: list[str] = []
    for restriction in restrictions:
        for reason in ingredient_violations(restriction, ingredient_names):
            out.append(f"{restriction}: {reason}")
    return out


def describe_enforcement(restriction: str) -> str:
    """One honest sentence on how a restriction is checked (or that it is not)."""
    if restriction in TAG_BACKED:
        return f"{restriction}: checked against the recipe's {restriction} tag."
    if restriction in INGREDIENT_ENFORCED:
        rule = INGREDIENT_ENFORCED[restriction]
        base = f"{restriction}: checked against the recipe's ingredient list."
        return f"{base} {rule.limitation}".strip()
    return f"{restriction}: NOT enforced. {UNENFORCED.get(restriction, 'The system cannot verify it.')}"


# Re-exported so callers have one import for the term sets this module is built from.
__all__ = [
    "FISH",
    "INGREDIENT_ENFORCED",
    "PARTIAL",
    "TAG_BACKED",
    "UNENFORCED",
    "SplitRestrictions",
    "describe_enforcement",
    "ingredient_violations",
    "split_restrictions",
    "violated_ingredient_restrictions",
]
