"""Pure, deterministic transformation logic for turning a TheMealDB recipe
record into MealSight's recipes.db row shape.

Nothing in this module makes a network call, touches a database, or calls
an LLM — every function here takes plain data in and returns plain data
out, which is what makes it possible to unit test all of it against fixed
inputs with no live API and no live database.
"""

from __future__ import annotations

import re
from typing import Literal

Importance = Literal["critical", "important", "optional"]

# ---------------------------------------------------------------------------
# Measure parsing
# ---------------------------------------------------------------------------

_UNICODE_FRACTIONS: dict[str, str] = {
    "¼": " 1/4", "½": " 1/2", "¾": " 3/4",
    "⅓": " 1/3", "⅔": " 2/3",
    "⅕": " 1/5", "⅖": " 2/5", "⅗": " 3/5", "⅘": " 4/5",
    "⅙": " 1/6", "⅚": " 5/6",
    "⅛": " 1/8", "⅜": " 3/8", "⅝": " 5/8", "⅞": " 7/8",
}

_NON_NUMERIC_MEASURES = {"", "to taste", "as needed", "for serving", "for garnish"}
_BARE_QUANTITY_WORDS = {"dash", "pinch", "handful", "splash"}

# Longer aliases first so e.g. "tablespoons" matches before "tsp" would ever
# get a chance to misfire on a shared prefix.
_UNIT_ALIASES: list[tuple[str, str]] = [
    ("tablespoons", "tbsp"), ("tablespoon", "tbsp"), ("tbsp", "tbsp"), ("tbsps", "tbsp"),
    ("teaspoons", "tsp"), ("teaspoon", "tsp"), ("tsp", "tsp"), ("tsps", "tsp"),
    ("kilograms", "kg"), ("kilogram", "kg"), ("kg", "kg"),
    ("grams", "g"), ("gram", "g"), ("g", "g"),
    ("milliliters", "ml"), ("millilitres", "ml"), ("ml", "ml"),
    ("liters", "l"), ("litres", "l"), ("liter", "l"), ("litre", "l"), ("l", "l"),
    ("ounces", "oz"), ("ounce", "oz"), ("oz", "oz"),
    ("pounds", "lb"), ("pound", "lb"), ("lbs", "lb"), ("lb", "lb"),
    ("cups", "cup"), ("cup", "cup"),
    ("cloves", "clove"), ("clove", "clove"),
    ("cans", "can"), ("can", "can"),
    ("slices", "slice"), ("slice", "slice"),
    ("sticks", "stick"), ("stick", "stick"),
    ("pinches", "pinch"), ("pinch", "pinch"),
    ("dashes", "dash"), ("dash", "dash"),
    ("pieces", "piece"), ("piece", "piece"),
    ("packets", "packet"), ("packet", "packet"),
    ("bunches", "bunch"), ("bunch", "bunch"),
    ("handfuls", "handful"), ("handful", "handful"),
]

_RANGE_RE = re.compile(
    r"^\s*(?P<low>\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+)\s*(?:-|to)\s*"
    r"(?P<high>\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+)"
)
_SINGLE_RE = re.compile(r"^\s*(?P<num>\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)")


def _parse_number_token(token: str) -> float:
    token = token.strip()
    if " " in token and "/" in token:
        whole_part, frac_part = token.split(" ", 1)
        numerator, denominator = frac_part.split("/")
        return int(whole_part) + int(numerator) / int(denominator)
    if "/" in token:
        numerator, denominator = token.split("/")
        return int(numerator) / int(denominator)
    return float(token)


def _normalize_unicode_fractions(text: str) -> str:
    for glyph, replacement in _UNICODE_FRACTIONS.items():
        text = text.replace(glyph, replacement)
    return text


def _find_unit(remainder: str) -> str | None:
    lowered = remainder.lower()
    for alias, canonical in _UNIT_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return canonical
    return None


def parse_measure(raw_measure: str | None) -> tuple[float | None, str | None]:
    """Parses a TheMealDB free-text measure like '1 tbsp', '1/2 cup',
    '400g', '2-3 tomatoes', or 'Dash' into (quantity, unit).

    Handles unicode fraction glyphs (½, ¼, ¾, ...) and ranges ("2-3",
    "2 to 3") by taking the midpoint. Returns (None, None) for measures
    that carry no usable quantity ("", "To taste"), and (None, unit) for
    bare-quantity words like "Dash" or "Pinch" that are meaningful units
    without a number attached.
    """
    if raw_measure is None:
        return None, None

    text = raw_measure.strip()
    normalized = text.lower()

    if normalized in _NON_NUMERIC_MEASURES:
        return None, None
    if normalized in _BARE_QUANTITY_WORDS:
        return None, normalized

    text = _normalize_unicode_fractions(text).strip()

    range_match = _RANGE_RE.match(text)
    if range_match:
        low = _parse_number_token(range_match.group("low"))
        high = _parse_number_token(range_match.group("high"))
        quantity: float | None = (low + high) / 2
        remainder = text[range_match.end() :]
        return quantity, _find_unit(remainder)

    single_match = _SINGLE_RE.match(text)
    if single_match:
        quantity = _parse_number_token(single_match.group("num"))
        remainder = text[single_match.end() :]
        return quantity, _find_unit(remainder)

    # No leading number at all (e.g. "Salt and pepper", "For frying") — no
    # quantity, but the whole phrase might still contain a recognizable unit.
    return None, _find_unit(text)


# ---------------------------------------------------------------------------
# Instruction splitting and cook-time estimation
# ---------------------------------------------------------------------------

_STEP_PREFIX_RE = re.compile(r"^step\s*\d+\.?\s*", re.IGNORECASE)

_DURATION_RE = re.compile(
    r"(?P<low>\d+)(?:\s*(?:-|to)\s*(?P<high>\d+))?\s*"
    r"(?P<unit>hours?|hrs?|minutes?|mins?|min)\b",
    re.IGNORECASE,
)

_COOKING_VERBS = (
    "bake", "roast", "simmer", "boil", "fry", "saute", "sauté", "grill",
    "stew", "braise", "steam", "poach", "broil", "marinate", "chill", "rest",
)

STEP_COUNT_BASE_MINUTES = 10
STEP_COUNT_PER_STEP_MINUTES = 5
COOKING_VERB_BONUS_MINUTES = 5
COOKING_VERB_BONUS_CAP_MINUTES = 30


def split_steps(raw_instructions: str) -> list[str]:
    """Splits TheMealDB's free-text strInstructions into an ordered list
    of instruction strings, stripping any 'STEP 1' / 'Step 2' style
    prefixes some recipes include."""
    text = raw_instructions.replace("\r\n", "\n").replace("\r", "\n")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    steps: list[str] = []
    for paragraph in paragraphs:
        cleaned = _STEP_PREFIX_RE.sub("", paragraph).strip()
        if cleaned:
            steps.append(cleaned)
    return steps


def estimate_cook_time_minutes(instructions: str, step_count: int) -> tuple[int, str]:
    """Estimates cook_time_minutes from instruction text.

    First tries to extract explicit durations ("simmer for 20 minutes",
    "bake for 45-50 mins") and sum them. If none are found, falls back to
    a heuristic based on step count plus a bonus per distinct cooking verb
    mentioned. Returns (minutes, source) where source records which path
    was used — this is what gets stored in cook_time_source.
    """
    total_minutes = 0.0
    found_any = False
    for match in _DURATION_RE.finditer(instructions):
        found_any = True
        low = int(match.group("low"))
        high_group = match.group("high")
        value = (low + int(high_group)) / 2 if high_group else float(low)
        unit = match.group("unit").lower()
        if unit.startswith("h"):
            value *= 60
        total_minutes += value

    if found_any and total_minutes > 0:
        return round(total_minutes), "extracted_from_instructions"

    lowered = instructions.lower()
    verb_bonus = min(
        COOKING_VERB_BONUS_CAP_MINUTES,
        sum(COOKING_VERB_BONUS_MINUTES for verb in _COOKING_VERBS if verb in lowered),
    )
    heuristic_minutes = STEP_COUNT_BASE_MINUTES + step_count * STEP_COUNT_PER_STEP_MINUTES + verb_bonus
    return heuristic_minutes, "heuristic_step_count_and_verbs"


# ---------------------------------------------------------------------------
# Ingredient importance assignment
# ---------------------------------------------------------------------------

# Garnishes, toppings, and seasonings — these are real, edible parts of the
# dish, just not what makes-or-breaks whether the recipe "works" if omitted
# or swapped. Matched as whole-word substrings against the normalized
# ingredient name.
GARNISH_AND_SEASONING_TERMS = frozenset(
    {
        "salt", "pepper", "black pepper", "white pepper", "salt and pepper",
        "parsley", "cilantro", "coriander leaves", "chives", "garnish",
        "sesame seeds", "sesame seed", "chilli flakes", "chili flakes",
        "red pepper flakes", "paprika", "cinnamon", "nutmeg", "sprinkle of",
        "lime wedge", "lemon wedge", "microgreens", "sprig", "zest",
        "cracked pepper", "sea salt", "kosher salt", "to garnish",
    }
)

PROTEIN_TERMS = frozenset(
    {
        "chicken", "beef", "pork", "lamb", "turkey", "duck", "goat", "veal",
        "shrimp", "prawn", "fish", "salmon", "tuna", "cod", "crab", "lobster",
        "squid", "octopus", "bacon", "sausage", "ham", "tofu", "tempeh",
        "egg", "eggs", "beans", "chickpeas", "lentils", "paneer",
    }
)


def _normalize_ingredient_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _matches_any_term_whole_word(name: str, terms: frozenset[str]) -> bool:
    """Whole-word/whole-phrase containment, not raw substring containment.

    Phase 2.2 verification found a real bug from plain `term in name`
    substring checks: "egg" (a PROTEIN_TERMS entry) matched inside
    "Parmigiano-Reggiano" (the substring "reggiano"[1:4] happens to spell
    "egg"), wrongly making a cheese garnish the recipe's one "critical"
    ingredient. \\b word-boundary matching only matches a term where it
    actually starts and ends a word (or, for a multi-word term like
    "black pepper", starts and ends that whole phrase) — "egg" no longer
    matches inside "reggiano" since there's no word boundary between the
    "r" before it and the "i" after it.

    An optional trailing "s" or "es" is tolerated (the same pluralization
    tolerance frontend/src/lib/wholeWordMatch.ts already applies for the
    identical reason — "prawn" needing to still match "prawns"): a strict
    \\bterm\\b alone would stop NUT_TERMS' own "peanut" from matching an
    ingredient literally named "Peanuts", since the trailing "s" removes
    the word boundary right after "peanut" that \\b requires. Found by a
    real, previously-passing test (test_peanuts_block_nut_free_tag)
    failing the moment whole-word matching replaced substring matching
    here — not spotted by inspection alone.
    """
    return any(re.search(rf"\b{re.escape(term)}(?:es|s)?\b", name) for term in terms)


# KNOWN_ISSUES.md #2's own real fix, built from an actual 15-recipe
# investigation of this exact corpus, not a speculative expansion: a
# curated, deliberately small set of non-protein STARCH/VEGETABLE terms
# that name a dish's own defining ingredient even when the English
# title never says so (Spanish Tortilla never says "potato"; Baingan
# Bharta never says "aubergine"). Checked as its own tier, between
# title-match and the protein-term fallback — the investigation found
# the protein fallback firing on a minor background ingredient (an egg
# in pierogi dough, a splash of chicken stock, a lentil filler) ahead of
# the dish's own real defining staple whenever that staple happened to
# sit later in the ingredient list than any protein-term match; putting
# this tier BEFORE the protein fallback, not after it, is what actually
# fixes that failure mode rather than just adding an alternative that
# never gets reached. Every term here traces to one of the 9 genuine
# misses that investigation found (6/15 sampled recipes reaching zero
# critical or the wrong one via protein-fallback, 3/15 reaching no
# critical ingredient at all) — "aubergine" not "eggplant" for the same
# reason MEAT_TERMS/DAIRY_TERMS already prefer this corpus's own real
# British vocabulary; "farfalle"/"fettuccine" alongside generic "pasta"
# because neither pasta SHAPE name contains the word "pasta" itself.
DEFINING_STAPLE_TERMS = frozenset(
    {"potato", "noodle", "pasta", "farfalle", "fettuccine", "squash", "aubergine"}
)


def assign_importances(recipe_name: str, ingredient_names: list[str]) -> list[Importance]:
    """Assigns critical/important/optional to each ingredient in a recipe,
    in the same order as ingredient_names, using an explicit rule set —
    no LLM, fully deterministic and reproducible for the same input.

    Rule, in order:
      1. At most one ingredient is "critical": the first one (in ingredient
         order) whose name appears in the recipe's own title; failing
         that, the first one matching a DEFINING_STAPLE_TERMS entry (a
         non-protein staple that names the dish even when the title
         doesn't); failing that, the first one matching a known
         PROTEIN_TERMS entry.
      2. Anything matching GARNISH_AND_SEASONING_TERMS is "optional" —
         *unless* it also matches a PROTEIN_TERMS word, in which case the
         protein match wins and it's "important" instead. Without this,
         "Salt Cod" gets marked optional purely because it contains the
         genuine whole word "salt", even though it's a defining protein
         ingredient, not a seasoning — the word "salt" doing double duty
         as both a seasoning and a real ingredient's prefix.
      3. Everything else is "important" (aromatics, sauces, and other core
         flavor components fall here by default).
    """
    normalized = [_normalize_ingredient_name(name) for name in ingredient_names]
    recipe_name_lower = recipe_name.lower()

    critical_index: int | None = None
    for index, name in enumerate(normalized):
        if name and name in recipe_name_lower:
            critical_index = index
            break
    if critical_index is None:
        for index, name in enumerate(normalized):
            if _matches_any_term_whole_word(name, DEFINING_STAPLE_TERMS):
                critical_index = index
                break
    if critical_index is None:
        for index, name in enumerate(normalized):
            if _matches_any_term_whole_word(name, PROTEIN_TERMS):
                critical_index = index
                break

    importances: list[Importance] = []
    for index, name in enumerate(normalized):
        if index == critical_index:
            importances.append("critical")
        elif _matches_any_term_whole_word(
            name, GARNISH_AND_SEASONING_TERMS
        ) and not _matches_any_term_whole_word(name, PROTEIN_TERMS):
            importances.append("optional")
        else:
            importances.append("important")
    return importances


# ---------------------------------------------------------------------------
# Dietary tag derivation
# ---------------------------------------------------------------------------

# Every term list below is intentionally a blocklist, not an allowlist:
# a recipe is tagged only when NONE of its ingredients match the relevant
# blocklist. An unrecognized, unusually-named ingredient simply doesn't
# match any term on any list, so it never by itself blocks a tag — but it
# also never earns one either, since every list here only ever removes a
# tag, never grants one. That asymmetry is the "conservative" part: silence
# from an ingredient we don't recognize is not treated as evidence in
# either direction, and no recipe on its ingredient list alone.
MEAT_TERMS = frozenset(
    {
        "chicken", "beef", "pork", "lamb", "turkey", "duck", "goat", "veal",
        "bacon", "sausage", "ham", "prosciutto", "salami", "pepperoni",
        "shrimp", "prawn", "fish", "salmon", "tuna", "cod", "crab", "lobster",
        "squid", "octopus", "anchovy", "anchovies",
        # American/British spelling pair, same convention as DAIRY_TERMS'
        # own "yogurt"/"yoghurt" — found switching to whole-word matching:
        # "gelatin" alone no longer matches "Gelatine Leafs" (a real
        # ingredient in the seeded corpus), since the trailing "e" isn't
        # covered by the s/es pluralization tolerance either. Listed
        # explicitly rather than widening the matching regex further.
        "gelatin", "gelatine", "lard",
        "chorizo", "mince", "ground beef", "ground pork", "ground turkey",
        "meat",
    }
)

DAIRY_TERMS = frozenset(
    {
        "milk", "butter", "cheese", "cream", "yogurt", "yoghurt", "ghee",
        "whey", "casein", "buttermilk", "parmesan", "mozzarella", "cheddar",
        "ricotta", "mascarpone", "cream cheese", "sour cream", "condensed milk",
        "evaporated milk", "half and half", "custard", "paneer",
    }
)

EGG_TERMS = frozenset({"egg", "eggs", "egg yolk", "egg white", "mayonnaise", "meringue"})

HONEY_TERMS = frozenset({"honey"})

# "flour"/"bread"/"noodle" are ambiguous — these prefixes make them
# gluten-free in practice, so a match here overrides a GLUTEN_TERMS hit.
_GLUTEN_SAFE_QUALIFIERS = frozenset(
    {"rice", "corn", "almond", "coconut", "chickpea", "gluten-free", "gluten free", "gf"}
)

GLUTEN_TERMS = frozenset(
    {
        "flour", "bread", "breadcrumb", "breadcrumbs", "pasta", "noodle",
        "noodles", "soy sauce", "wheat", "barley", "rye", "couscous",
        "cracker", "crackers", "beer", "malt", "seitan", "spaghetti",
        "macaroni", "udon", "ramen",
    }
)

# Coconut is botanically a drupe, not a tree nut, and major allergen
# labeling schemes (including the US FDA's) list it separately from tree
# nuts — so it's deliberately excluded from NUT_TERMS.
NUT_TERMS = frozenset(
    {
        "almond", "peanut", "cashew", "walnut", "pecan", "pistachio",
        "hazelnut", "macadamia", "pine nut", "brazil nut", "nutella",
        "marzipan", "nut butter", "praline",
    }
)


def _any_term_matches(ingredient_names: list[str], terms: frozenset[str]) -> bool:
    """Whole-word matching (see _matches_any_term_whole_word's own
    docstring for the real "reggiano" contains "egg" bug this same
    pattern was fixed for in assign_importances) — not raw substring
    containment. Every one of this module's five dietary-tag blocklists
    (MEAT_TERMS, DAIRY_TERMS, EGG_TERMS, HONEY_TERMS, NUT_TERMS) runs
    through here, so "eggplant" no longer falsely matches EGG_TERMS'
    own "egg" entry."""
    normalized = [_normalize_ingredient_name(name) for name in ingredient_names]
    return any(_matches_any_term_whole_word(name, terms) for name in normalized)


def _has_unsafe_gluten_ingredient(ingredient_names: list[str]) -> bool:
    """GLUTEN_TERMS and _GLUTEN_SAFE_QUALIFIERS carry the identical
    substring-matching risk the other five blocklists had — found while
    fixing those (this file's own sixth term-list pair, not one of the
    five KNOWN_ISSUES.md itself named): raw `term in name` would let
    GLUTEN_TERMS' own "wheat" falsely match inside "buckwheat" (a real
    pseudocereal, genuinely gluten-free despite the name), wrongly
    denying a recipe the gluten_free tag it should get. Whole-word
    matching fixes that the same way it fixes "eggplant"."""
    for name in ingredient_names:
        normalized = _normalize_ingredient_name(name)
        has_gluten_term = _matches_any_term_whole_word(normalized, GLUTEN_TERMS)
        has_safe_qualifier = _matches_any_term_whole_word(normalized, _GLUTEN_SAFE_QUALIFIERS)
        if has_gluten_term and not has_safe_qualifier:
            return True
    return False


def derive_dietary_tags(ingredient_names: list[str]) -> list[str]:
    """Derives dietary_tags from a recipe's ingredient names using
    conservative blocklist logic: a tag is only applied when nothing in
    the ingredient list matches a term that would rule it out. Returns
    tags in a fixed, deterministic order."""
    tags: list[str] = []

    is_meat_free = not _any_term_matches(ingredient_names, MEAT_TERMS)
    is_dairy_free = not _any_term_matches(ingredient_names, DAIRY_TERMS)
    is_egg_free = not _any_term_matches(ingredient_names, EGG_TERMS)
    is_honey_free = not _any_term_matches(ingredient_names, HONEY_TERMS)

    if is_meat_free:
        tags.append("vegetarian")
    if is_meat_free and is_dairy_free and is_egg_free and is_honey_free:
        tags.append("vegan")
    if is_dairy_free:
        tags.append("dairy_free")
    if not _has_unsafe_gluten_ingredient(ingredient_names):
        tags.append("gluten_free")
    if not _any_term_matches(ingredient_names, NUT_TERMS):
        tags.append("nut_free")

    return tags


# ---------------------------------------------------------------------------
# Category / area mapping
# ---------------------------------------------------------------------------

# TheMealDB has no true "meal type" (breakfast/lunch/dinner) field — its
# strCategory is the closest available signal, so this is an approximation,
# not a precise mapping. Categories that are really protein/course types
# rather than meal times default to "main".
CATEGORY_TO_MEAL_TYPE: dict[str, str] = {
    "Breakfast": "breakfast",
    "Dessert": "dessert",
    "Starter": "appetizer",
    "Side": "side",
    "Beef": "main",
    "Chicken": "main",
    "Lamb": "main",
    "Pork": "main",
    "Goat": "main",
    "Seafood": "main",
    "Pasta": "main",
    "Vegetarian": "main",
    "Vegan": "main",
    "Miscellaneous": "main",
}


def map_category_to_meal_type(category: str | None) -> str | None:
    if category is None:
        return None
    return CATEGORY_TO_MEAL_TYPE.get(category, "main")


def map_area_to_cuisine(area: str | None, country: str | None) -> str | None:
    if area:
        return area
    return country
