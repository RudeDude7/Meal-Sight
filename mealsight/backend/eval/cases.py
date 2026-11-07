"""Dimension 2's test cases (30 original, plus 10 cuisine cases added after the first run, see
below) — every one a natural-language text_input, run through the real agent pipeline exactly as a genuine
user request would be (extraction included, not bypassed). Coverage
per the task: single dietary restrictions, multiple simultaneous
restrictions, time limits, servings, avoid-ingredient lists,
avoid-dish lists, and combinations of those — plus cases designed to
be unsatisfiable, where honest refusal is the correct, passing outcome.

expect_refusal is an authored judgment about whether a case COULD be
satisfied by the real 250-recipe corpus, not a guess: the two
gluten_free/nut_free/vegan-stacked cases below are unsatisfiable
because mealsight.seed.recipe_parsing.derive_dietary_tags only ever
produces 5 corpus tags (vegetarian, vegan, dairy_free, gluten_free,
nut_free) and stacking three of them against a tight cook-time ceiling
was already confirmed empty against the real corpus in an earlier
phase's own meal-planning verification work. cuisine_preference is
the one soft-scored constraint (per the task) — cases that set one
record it in cuisine_soft so dimension2.py can score it separately
from the binary hard-constraint pass/fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Case:
    case_id: str
    description: str
    text_input: str
    expect_refusal: bool
    cuisine_soft: str | None = field(default=None)
    # Authored ground truth for what the request actually asks, independent
    # of what the pipeline's own extraction step managed to pull out.
    dietary: tuple[str, ...] = ()
    max_minutes: int | None = None
    servings: int | None = None
    avoid_ingredients: tuple[str, ...] = ()
    avoid_dishes: tuple[str, ...] = ()
    # Set when the authored expect_refusal was corrected after a run showed it
    # was wrong. The original value stays in _BASE_CASES; see CORRECTIONS.
    expectation_note: str = ""
    # For cases with cuisine_soft: whether the seeded pantry can cook a recipe of that cuisine that
    # satisfies the request's hard constraints (checked against the cookable list, 22 of 250 recipes).
    # None when the case sets no cuisine. Lets the soft score separate a miss that was avoidable
    # from an honest miss that no recommendation could have avoided.
    cuisine_attainable: bool | None = None


_BASE_CASES: list[Case] = [
    # --- single dietary restriction (6) ---
    Case("d2_01", "single restriction: vegetarian", "I need a vegetarian dinner for tonight.", False),
    Case("d2_02", "single restriction: vegan", "Give me a vegan recipe.", False),
    Case("d2_03", "single restriction: gluten-free", "I need something gluten-free to cook.", False),
    Case("d2_04", "single restriction: dairy-free", "Find me a dairy-free recipe.", False),
    Case(
        "d2_05",
        "single restriction: nut-free",
        "I need a nut-free meal, someone here has a nut allergy.",
        False,
    ),
    Case(
        "d2_06",
        "single restriction: keto (unsupported by corpus tags)",
        "I need a keto recipe.",
        True,
    ),
    # --- multiple simultaneous restrictions (5) ---
    Case("d2_07", "vegan + gluten-free", "I need something vegan and gluten-free.", False),
    Case("d2_08", "vegetarian + dairy-free", "Vegetarian and dairy-free please, no dairy at all.", False),
    Case("d2_09", "vegan + nut-free", "I need a vegan recipe with no nuts, nut allergy in the house.", False),
    Case(
        "d2_10",
        "vegan + gluten-free + nut-free (unsatisfiable combo)",
        "I need something vegan, gluten-free, and nut-free.",
        True,
    ),
    Case("d2_11", "gluten-free + dairy-free", "I need a gluten-free and dairy-free dinner.", False),
    # --- time limits (5) ---
    Case("d2_12", "15 minute limit", "I only have 15 minutes, what can I make?", False),
    Case("d2_13", "20 minute limit", "Something quick, 20 minutes max.", False),
    Case("d2_14", "30 minute limit", "I need dinner in 30 minutes or less.", False),
    Case(
        "d2_15",
        "10 minute limit stacked with vegan + gluten-free + nut-free (unsatisfiable)",
        "I need something vegan, gluten-free, and nut-free, ready in 10 minutes.",
        True,
    ),
    Case("d2_16", "45 minute limit", "I have 45 minutes for dinner tonight.", False),
    # --- servings (4) ---
    Case("d2_17", "servings: 2", "I need a recipe for 2 people.", False),
    Case("d2_18", "servings: 4", "Cooking for 4 people tonight.", False),
    Case("d2_19", "servings: 6", "I need to feed 6 people.", False),
    Case("d2_20", "servings: 1", "Just cooking for myself, 1 serving.", False),
    # --- avoid-ingredient lists (4) ---
    Case(
        "d2_21",
        "avoid single ingredient: cilantro",
        "I need a recipe but please avoid cilantro, I hate it.",
        False,
    ),
    Case(
        "d2_22",
        "avoid multiple ingredients: mushrooms and olives",
        "Find me something to cook, but avoid mushrooms and olives.",
        False,
    ),
    Case(
        "d2_23",
        "avoid ingredient: shellfish (allergy)",
        "I have a shellfish allergy, avoid shellfish entirely.",
        False,
    ),
    Case(
        "d2_24",
        "avoid ingredient: peanuts, stacked with vegetarian",
        "I need a vegetarian recipe, and please avoid peanuts, allergy.",
        False,
    ),
    # --- avoid-dish lists (3) ---
    Case("d2_25", "avoid dish: salad", "I want dinner tonight but not a salad, I'm tired of salads.", False),
    Case("d2_26", "avoid dish: soup", "Anything but soup for dinner please.", False),
    Case(
        "d2_27",
        "avoid dish: stir fry, stacked with 20 minute limit",
        "I need something in 20 minutes, but not a stir fry.",
        False,
    ),
    # --- combinations / cuisine soft constraint (3) ---
    Case(
        "d2_28",
        "cuisine preference (soft) + vegetarian (hard)",
        "I'd like an Italian vegetarian dinner.",
        False,
        cuisine_soft="italian",
    ),
    Case(
        "d2_29",
        "cuisine preference (soft) + 30 minute limit + servings 4",
        "I want Mexican food, 30 minutes or less, for 4 people.",
        False,
        cuisine_soft="mexican",
    ),
    Case(
        "d2_30",
        "full combination: vegan, dairy-free, avoid mushrooms, 30 minutes, 2 servings",
        "I need something vegan and dairy-free, no mushrooms, ready in 30 minutes, for 2 people.",
        False,
    ),
]

# What each request actually asks for, written by hand from the request text
# (not read back from the pipeline's extraction). Dietary values use the
# corpus's underscore tag spelling.
_AUTHORED: dict[str, dict[str, object]] = {
    "d2_01": {"dietary": ("vegetarian",)},
    "d2_02": {"dietary": ("vegan",)},
    "d2_03": {"dietary": ("gluten_free",)},
    "d2_04": {"dietary": ("dairy_free",)},
    "d2_05": {"dietary": ("nut_free",)},
    "d2_06": {"dietary": ("keto",)},
    "d2_07": {"dietary": ("vegan", "gluten_free")},
    "d2_08": {"dietary": ("vegetarian", "dairy_free")},
    "d2_09": {"dietary": ("vegan", "nut_free")},
    "d2_10": {"dietary": ("vegan", "gluten_free", "nut_free")},
    "d2_11": {"dietary": ("gluten_free", "dairy_free")},
    "d2_12": {"max_minutes": 15},
    "d2_13": {"max_minutes": 20},
    "d2_14": {"max_minutes": 30},
    "d2_15": {"dietary": ("vegan", "gluten_free", "nut_free"), "max_minutes": 10},
    "d2_16": {"max_minutes": 45},
    "d2_17": {"servings": 2},
    "d2_18": {"servings": 4},
    "d2_19": {"servings": 6},
    "d2_20": {"servings": 1},
    "d2_21": {"avoid_ingredients": ("cilantro",)},
    "d2_22": {"avoid_ingredients": ("mushrooms", "olives")},
    "d2_23": {"avoid_ingredients": ("shellfish",)},
    "d2_24": {"dietary": ("vegetarian",), "avoid_ingredients": ("peanuts",)},
    "d2_25": {"avoid_dishes": ("salad",)},
    "d2_26": {"avoid_dishes": ("soup",)},
    "d2_27": {"max_minutes": 20, "avoid_dishes": ("stir fry",)},
    "d2_28": {"dietary": ("vegetarian",)},
    "d2_29": {"max_minutes": 30, "servings": 4},
    "d2_30": {
        "dietary": ("vegan", "dairy_free"),
        "avoid_ingredients": ("mushrooms",),
        "max_minutes": 30,
        "servings": 2,
    },
}

# Expectation corrections, made AFTER the first full Dimension 2 run
# (run_1793926853, 2026-11-06) showed three authored expect_refusal values
# were wrong against the seeded pantry (fixture hash 756090ab287f; 22 of 250
# recipes cookable). Each was verified by listing the cookable recipes that
# satisfy only what the request states. The original values are kept in
# _BASE_CASES above; nothing was changed to make a result pass, and the first
# run's scorecard keeps the original expectations.
CORRECTIONS: dict[str, dict[str, object]] = {
    "d2_10": {
        "expect_refusal": False,
        "expectation_note": (
            "Was expect_refusal=True. Boulangere Potatoes (60 min) is cookable and tagged vegan, "
            "gluten_free and nut_free; the request states no time, so it is satisfiable. The first run "
            "'passed' it only because a 30-minute profile default (not stated by the user) excluded it."
        ),
    },
    "d2_12": {
        "expect_refusal": True,
        "expectation_note": (
            "Was expect_refusal=False. Of the 22 recipes cookable from the seeded pantry, none takes 15 "
            "minutes or less (the quickest is 20), so honest refusal is correct for this pantry."
        ),
    },
    "d2_06": {
        "expect_refusal": False,
        "expectation_note": (
            "Was expect_refusal=True (the corpus has no keto tag, so every recipe was filtered out). "
            "Changed by the dietary-enforcement fix: tag filters now cover only the five tags the corpus "
            "has, and keto is declared UNENFORCED (nutrition estimates are not reliable enough to "
            "filter on). The request is now answered with a recommendation that must state 'NOT "
            "ENFORCED: keto'; the scorer fails the case if that disclosure is missing."
        ),
    },
    "d2_30": {
        "expect_refusal": True,
        "expectation_note": (
            "Was expect_refusal=False. The only cookable vegan + dairy_free recipe is Boulangere Potatoes "
            "at 60 minutes and the request states a 30-minute limit, so nothing cookable satisfies it."
        ),
    },
}

_AUTHORED["d2_28"] = {**_AUTHORED.get("d2_28", {}), "cuisine_attainable": True}  # Pizza Express Margherita
_AUTHORED["d2_29"] = {
    **_AUTHORED.get("d2_29", {}),
    "cuisine_attainable": False,
}  # no Mexican recipe is cookable

# Added AFTER the first Dimension 2 run (run_1793926853, 2026-11-06), because
# the soft cuisine score then rested on two cases (one hit, one miss = 0.5),
# which is not a measurement. Ten cuisine cases added, written and labelled
# BEFORE being run, against the seeded pantry (fixture hash 756090ab287f):
#   attainable (a cookable recipe of that cuisine satisfies the hard
#   constraints): Indian (Chicken Handi), British (5 recipes), French (French
#   Onion Soup, no mushrooms), Turkish (Kumpir), Jamaican (Brown Stew Chicken),
#   Italian (Pizza Express Margherita);
#   NOT attainable (no recipe of the cuisine is cookable from this pantry):
#   Thai, Japanese + gluten-free, Chinese + 30 min, Greek + vegetarian.
# For the unattainable ones the correct outcome is a recommendation of some
# other cuisine with no hard violation (an honest miss), not a refusal.
_ADDED_AFTER_FIRST_RUN: list[Case] = [
    Case(
        "d2_31",
        "cuisine (attainable): Indian",
        "I'd like Indian food tonight.",
        False,
        cuisine_soft="india",
        cuisine_attainable=True,
    ),
    Case(
        "d2_32",
        "cuisine (attainable): British",
        "I want something British for dinner.",
        False,
        cuisine_soft="british",
        cuisine_attainable=True,
    ),
    Case(
        "d2_33",
        "cuisine (attainable): French + avoid mushrooms",
        "French food please, no mushrooms.",
        False,
        cuisine_soft="france",
        avoid_ingredients=("mushroom",),
        cuisine_attainable=True,
    ),
    Case(
        "d2_34",
        "cuisine (attainable): Turkish",
        "Something Turkish, please.",
        False,
        cuisine_soft="turkish",
        cuisine_attainable=True,
    ),
    Case(
        "d2_35",
        "cuisine (attainable): Jamaican",
        "I'm in the mood for Jamaican food.",
        False,
        cuisine_soft="jamaican",
        cuisine_attainable=True,
    ),
    Case(
        "d2_36",
        "cuisine (attainable): Italian, no other constraint",
        "Italian food please.",
        False,
        cuisine_soft="italian",
        cuisine_attainable=True,
    ),
    Case(
        "d2_37",
        "cuisine (NOT attainable): Thai",
        "I want Thai food.",
        False,
        cuisine_soft="thai",
        cuisine_attainable=False,
    ),
    Case(
        "d2_38",
        "cuisine (NOT attainable): Japanese + gluten-free",
        "Japanese dinner, and it has to be gluten-free.",
        False,
        cuisine_soft="japanese",
        dietary=("gluten_free",),
        cuisine_attainable=False,
    ),
    Case(
        "d2_39",
        "cuisine (NOT attainable): Chinese + 30 minutes",
        "Chinese food, 30 minutes or less.",
        False,
        cuisine_soft="chinese",
        max_minutes=30,
        cuisine_attainable=False,
    ),
    Case(
        "d2_40",
        "cuisine (NOT attainable): Greek + vegetarian",
        "I'd like a Greek vegetarian dinner.",
        False,
        cuisine_soft="greek",
        dietary=("vegetarian",),
        cuisine_attainable=False,
    ),
]

# Added AFTER the cuisine-label fix (2026-11-06), once run_1793975487 showed that
# "Indian" and "French" never matched the corpus labels "India" and "France"
# (d2_31 was told no Indian recipe existed while Chicken Handi was cookable;
# d2_33's "hit" was luck). One case per remaining name form the corpus does not
# use, labelled against the cookable list BEFORE being run:
#   American -> corpus "United States": attainable (Chick-Fil-A Sandwich, 32 min;
#     Skillet Apple Pork Chops, 48; French Onion Chicken, 50; ...)
#   Dutch -> corpus "Netherlands": NOT attainable (no Netherlands recipe is cookable)
#   "from Ireland" -> corpus "Irish" (the country form for a demonym label, the
#     reverse direction): attainable (Corned Beef and Cabbage, 65 min)
_ADDED_AFTER_CUISINE_FIX: list[Case] = [
    Case(
        "d2_41",
        "cuisine (attainable): American -> 'United States'",
        "I'd like American food tonight.",
        False,
        cuisine_soft="united states",
        cuisine_attainable=True,
    ),
    Case(
        "d2_42",
        "cuisine (NOT attainable): Dutch -> 'Netherlands'",
        "I want a Dutch dish.",
        False,
        cuisine_soft="netherlands",
        cuisine_attainable=False,
    ),
    Case(
        "d2_43",
        "cuisine (attainable): country form 'Ireland' -> 'Irish'",
        "Something from Ireland, please.",
        False,
        cuisine_soft="irish",
        cuisine_attainable=True,
    ),
]

# Added AFTER the dietary-enforcement fix (2026-11-06). Twelve of the seventeen restrictions in the
# extraction vocabulary had no corpus tag and were sent to search as tag filters that matched nothing,
# so a request carrying one was refused. They are now enforced against ingredient lists, or declared
# UNENFORCED and disclosed (mealsight.matching.diet). Labelled against the cookable list (22 of 250
# recipes, fixture hash 756090ab287f) BEFORE being run; "violators" are cookable recipes that break the
# restriction, i.e. ones the exclusion must actually remove (not pass by absence):
#   peanut-free   : 22 cookable satisfy, 0 cookable violate (9 in the corpus do) -> attainable
#   soy-free      : 20 satisfy, 2 cookable violate (Brown Stew Chicken, Soy-Glazed Meatloaves) -> attainable
#   egg-free      : 19 satisfy, 3 cookable violate (Beef Sunday Roast, Minced Beef Pie, Chick-Fil-A)
#   shellfish-free: 22 satisfy, 0 cookable violate -> attainable
#   pescatarian   : 9 satisfy, 13 cookable violate (Chicken Handi, Beef Sunday Roast, ...) -> attainable
#   halal         : 18 satisfy, 4 cookable violate (French Onion Soup [wine], Pear Tarte Tatin [brandy], ...)
#   kosher        : 11 satisfy, 11 cookable violate (meat with dairy) -> attainable
#   pescatarian + gluten-free: Creamy Tomato Soup, Boulangere, Pear Tarte Tatin, Kumpir -> attainable
#   kosher + 30 min: Creamy Tomato Soup (28 min) -> attainable
#   pescatarian + 15 min: nothing cookable is under 20 minutes -> NOT attainable, correct refusal
#   low-sodium, low-carb: declared unenforced -> a recommendation that DISCLOSES it (scorer enforces this)
# halal and kosher are partial checks; the scorer also requires the answer to say what is not verified.
_ADDED_AFTER_DIET_FIX: list[Case] = [
    Case(
        "d2_44",
        "peanut-free (ingredient-enforced)",
        "I have a peanut allergy, nothing with peanuts please.",
        False,
        dietary=("peanut_free",),
    ),
    Case(
        "d2_45",
        "soy-free: cookable violators exist",
        "I'm allergic to soy, no soy at all.",
        False,
        dietary=("soy_free",),
    ),
    Case(
        "d2_46",
        "egg-free: cookable violators exist",
        "I can't eat eggs, egg-free please.",
        False,
        dietary=("egg_free",),
    ),
    Case("d2_47", "shellfish-free", "I need a shellfish-free dinner.", False, dietary=("shellfish_free",)),
    Case(
        "d2_48",
        "pescatarian: many cookable violators",
        "I'm pescatarian, what can I cook tonight?",
        False,
        dietary=("pescatarian",),
    ),
    Case("d2_49", "halal (partial: pork + alcohol)", "I need a halal dinner.", False, dietary=("halal",)),
    Case(
        "d2_50",
        "kosher (partial: pork, shellfish, meat+dairy)",
        "I need a kosher dinner.",
        False,
        dietary=("kosher",),
    ),
    Case(
        "d2_51",
        "pescatarian + gluten-free",
        "I'm pescatarian and gluten-free.",
        False,
        dietary=("pescatarian", "gluten_free"),
    ),
    Case(
        "d2_52",
        "low-sodium: unenforced, must be disclosed",
        "I need something low-sodium.",
        False,
        dietary=("low_sodium",),
    ),
    Case(
        "d2_53",
        "low-carb: unenforced, must be disclosed",
        "I'm doing low-carb this week.",
        False,
        dietary=("low_carb",),
    ),
    Case(
        "d2_54",
        "pescatarian + 15 minutes (nothing cookable)",
        "I'm pescatarian and I only have 15 minutes.",
        True,
        dietary=("pescatarian",),
        max_minutes=15,
    ),
    Case(
        "d2_55",
        "kosher + 30 minutes",
        "I need a kosher dinner in 30 minutes or less.",
        False,
        dietary=("kosher",),
        max_minutes=30,
    ),
]

CASES: list[Case] = (
    [
        replace(c, **{**_AUTHORED.get(c.case_id, {}), **CORRECTIONS.get(c.case_id, {})})  # type: ignore[arg-type]
        for c in _BASE_CASES
    ]
    + _ADDED_AFTER_FIRST_RUN
    + _ADDED_AFTER_CUISINE_FIX
    + _ADDED_AFTER_DIET_FIX
)

assert len(_BASE_CASES) == 30  # the original set, unchanged
assert len(CASES) == 55  # + 10 cuisine cases, + 3 after the cuisine fix, + 12 after the dietary fix
assert len({c.case_id for c in CASES}) == 55
