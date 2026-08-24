"""resolve_category — determines an ingredient's grocery/shelf-life
category (protein, vegetable, fruit, dairy, grain, condiment, spice,
other) independent of shelf_life_reference.

Why this is its own module rather than just reading shelf_life_
reference.category: a grocery list needs a section for EVERY missing
ingredient, but shelf_life_reference only has a row for items someone
bothered to curate real shelf-life numbers for. Coupling section
assignment to that table meant a real ingredient with no shelf-life data
yet (a new recipe, a new vision-vocabulary term) silently fell into
"other" — not because it was actually uncategorizable, just because
nobody had entered its refrigerated/frozen/pantry days yet. This module
separates the two concerns: resolve_category answers "what kind of thing
is this" using three fallback layers, cheapest and most reliable first;
mealsight.pantry.shelf_life.resolve_shelf_life answers "how long does it
last," a genuinely separate question only perishables need answered at
all.

Priority order:
  1. An exact shelf_life_reference row, if one exists — reference data
     someone already curated is the most trustworthy source, whenever
     it happens to be available.
  2. EXPLICIT_CATEGORY_MAP — hand-authored for specific ingredients the
     keyword rules below would get wrong or miss entirely (a plain
     "water" isn't any of the eight buckets; "corn" is vegetable, not
     grain, even though "corn flour" — a real GRAIN_TERMS hit — is).
  3. Keyword rules over the canonical name, using \\b word-boundary
     matching (never raw substring containment — see
     mealsight.seed.recipe_parsing._matches_any_term_whole_word's own
     docstring for the exact "egg" inside "reggiano" bug this avoids).
  4. "other", if nothing above matched anything.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from mealsight.pantry.shelf_life import ShelfLifeEntry
from mealsight.seed.recipe_parsing import DAIRY_TERMS, PROTEIN_TERMS

Category = str  # protein | vegetable | fruit | dairy | grain | condiment | spice | other

# Specific ingredients the keyword rules below would either miss
# entirely or misclassify — checked before any keyword rule runs.
EXPLICIT_CATEGORY_MAP: dict[str, Category] = {
    "water": "other",
    "boiling water": "other",
    "corn": "vegetable",
    "sweetcorn": "vegetable",
    "creamed corn": "vegetable",
    "oil": "condiment",
    "salt": "spice",
    "pepper": "spice",
    "black pepper": "spice",
    "sugar": "condiment",
    "honey": "condiment",
    "vinegar": "condiment",
    "mayonnaise": "condiment",
    "coconut": "fruit",
    "coconut milk": "condiment",
    "coconut cream": "condiment",
    "almond milk": "dairy",
    "soya milk": "dairy",
    "tofu": "protein",
    "tempeh": "protein",
    "gelatin": "condiment",
    "gelatine leaf": "condiment",
}

# Terms unique to this module — the dairy/protein lists above are
# reused directly from mealsight.seed.recipe_parsing rather than
# duplicated, since those are already tested against real substring-
# collision bugs; there's no equivalent existing list for these four
# categories to reuse instead.
VEGETABLE_TERMS = frozenset(
    {
        "onion", "garlic", "potato", "carrot", "celery", "tomato", "pepper",
        "mushroom", "broccoli", "cabbage", "spinach", "lettuce", "cucumber",
        "courgette", "zucchini", "cauliflower", "eggplant", "aubergine",
        "beet", "beetroot", "radish", "asparagus", "avocado", "leek",
        "shallot", "squash", "pumpkin", "kale", "chard", "artichoke",
        "turnip", "swede", "rocket", "arugula", "sprout", "gourd", "chilli",
        "chili", "jalapeno", "scallion",
    }
)

FRUIT_TERMS = frozenset(
    {
        "apple", "banana", "orange", "lemon", "lime", "strawberry",
        "blueberry", "grape", "pear", "peach", "mango", "cherry",
        "raspberry", "blackberry", "apricot", "plum", "melon", "watermelon",
        "pineapple", "kiwi", "fig", "date", "currant", "raisin", "sultana",
        "rhubarb", "nectarine", "cranberry",
    }
)

GRAIN_TERMS = frozenset(
    {
        "flour", "bread", "rice", "pasta", "noodle", "wheat", "barley",
        "rye", "oat", "couscous", "quinoa", "cracker", "biscuit", "cereal",
        "tortilla", "pastry", "dough", "macaroni", "spaghetti", "penne",
        "cornflour", "cornstarch", "lentil", "chickpea", "bean", "almond",
        "walnut", "cashew", "pecan", "hazelnut", "pine nut", "granola",
        "muesli",
    }
)

CONDIMENT_TERMS = frozenset(
    {
        "sauce", "ketchup", "mustard", "syrup", "jam", "stock", "broth",
        "paste", "gravy", "dressing", "marinade", "chutney", "pickle",
        "wine", "beer", "spirit", "liqueur",
    }
)

SPICE_TERMS = frozenset(
    {
        "paprika", "cinnamon", "nutmeg", "cumin", "oregano", "basil",
        "thyme", "rosemary", "sage", "dill", "parsley", "cilantro",
        "coriander", "turmeric", "cardamom", "clove", "allspice", "saffron",
        "vanilla", "seasoning", "spice", "extract", "bay leaf",
    }
)

# Checked in this order — dairy and protein first (borrowed from
# recipe_parsing, already hardened against substring bugs), then the
# four category-specific lists above, spice last since flavoring words
# ("extract", "seasoning") are the most generic and likeliest to
# false-match something that's really one of the earlier categories.
_KEYWORD_RULES: tuple[tuple[Category, frozenset[str]], ...] = (
    ("dairy", DAIRY_TERMS),
    ("protein", PROTEIN_TERMS),
    ("grain", GRAIN_TERMS),
    ("vegetable", VEGETABLE_TERMS),
    ("fruit", FRUIT_TERMS),
    ("condiment", CONDIMENT_TERMS),
    ("spice", SPICE_TERMS),
)


def _matches_any_term_whole_word(name: str, terms: frozenset[str]) -> bool:
    """Whole-word/whole-phrase containment, not raw substring
    containment — the same discipline mealsight.seed.recipe_parsing's
    own _matches_any_term_whole_word uses, and for the identical reason:
    a raw `term in name` check would let "egg" match inside "reggiano"."""
    return any(re.search(rf"\b{re.escape(term)}\b", name) for term in terms)


def resolve_category(
    canonical_name: str, shelf_life_map: Mapping[str, ShelfLifeEntry]
) -> Category:
    """Resolves canonical_name to one of protein/vegetable/fruit/dairy/
    grain/condiment/spice/other, using an exact shelf_life_reference row
    first, then EXPLICIT_CATEGORY_MAP, then whole-word keyword rules,
    then "other" as the final fallback."""
    entry = shelf_life_map.get(canonical_name)
    if entry is not None:
        return entry.category

    explicit = EXPLICIT_CATEGORY_MAP.get(canonical_name)
    if explicit is not None:
        return explicit

    for category, terms in _KEYWORD_RULES:
        if _matches_any_term_whole_word(canonical_name, terms):
            return category

    return "other"
