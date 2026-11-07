# ruff: noqa: E501  (hand-written derivation prose)
"""Dimension 5's 15 personalization cases.

THE QUESTION. After a profile is seeded, do recommendations align with it?

DESIGN. Every case runs the real pipeline against a throwaway pantry and a freshly seeded profile
(eval/isolation.py). Most cases use a PAIR of recipes whose ingredients are the whole pantry, so
both are 1.0 matches and, under default scoring, tie exactly (same match, no expiring items, same
cook-time class, neutral cuisine). Only the profile signal can break the tie. The same pair is
used with OPPOSITE profiles wherever possible, so a system that ignores the profile cannot pass
both by luck. Where a profile signal is not a tie-breaker but must beat a default (a disliked
ingredient in the recipe the default scoring would otherwise pick), the case says so.

THE PAIRS (cookable, 1.0 matches; checked against the whole corpus by eval/analysis.py):
  P1  Spaghetti alla Carbonara (Italian, 15 min, bacon)   vs  Honey Teriyaki Salmon (Japanese, 30 min, salmon)
      both within a 30-minute default: tied at composite 0.825.
  P2  Spaghetti alla Carbonara (15 min)                   vs  Chicken Enchilada Casserole (Mexican, 45 min, chicken)
      Carbonara leads by the 0.15 cook-time nudge.
  P3  Honey Teriyaki Salmon (30 min)                      vs  Chicken Enchilada Casserole (45 min)
      Salmon leads by the nudge.
  P4  Fettucine alfredo (Italian, 4 min, cream)           vs  Mbuzi Choma (Kenyan, 60 min, goat)
      Fettucine leads by the nudge.
  P5  Chicken Enchilada Casserole (45 min)                vs  Baked salmon with fennel & tomatoes (British, 35 min)
      both over 30 minutes: tied at composite 0.675.
  P6  Kumpir (Turkish, 25 min)                            vs  Spaghetti alla Carbonara (15 min)

SEEDING. Cuisine preferences are learned the way the product learns them: meals are logged with
ratings and the system recomputes the scores. Seeded meals are dated 40+ days ago so they cannot
trigger repetition, and carry no recipe id or ingredients so they cannot trigger protein counting.
The number of ratings per cuisine (data_points) is stated in each case, and 10 five-star ratings
shrink to 0.885 (and 10 one-star ratings to 0.115) under the product's prior of 3 neutral ratings:
a confident preference, not a single data point.

EXPECTED OUTCOMES were derived by hand from the rules and the pairs above before any run. Each case
names the recipe(s) that satisfy the profile signal (`aligned`) and derives the expected composite
by hand. The harness recomputes the set of aligned, cookable recipes from the whole corpus and
checks it contains `aligned`; if not the case is reported as a case defect, never as a system failure.

VERDICT (for the recommended recipe R, with P the cookable recipes that honour the profile signal):
  no_feasible_option   P is empty: nothing could honour the signal. Pass.
  aligned              R is in P. Pass.
  justified            R is not in P but its hand composite beats every recipe in P (a far better match correctly
                       outweighs a soft preference). Pass. Never available for a stored dislike or a repeat, which
                       are not trade-offs.
  misaligned           otherwise. Fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.isolation import MealSeed, ProfileSeed

# Recipe ids of the pair members (corpus ids).
CARBONARA = "52982"
SALMON = "52773"
ENCHILADA = "52765"
FETTUCINE = "52835"
MBUZI = "52968"
BAKED_SALMON = "52959"
KUMPIR = "52978"
BOULANGERE = "52914"


@dataclass(frozen=True)
class PantrySpec:
    """The pantry is the union of these recipes' ingredient lists (so each is a 1.0 match), plus extras."""

    recipes: tuple[str, ...]
    extra: tuple[str, ...] = ()


@dataclass(frozen=True)
class Aspect:
    kind: str  # cuisine | dislike | protein | household | quick | soft_time | repeat_recipe | repeat_protein
    value: str | int


@dataclass(frozen=True)
class PersonalizationCase:
    case_id: str
    description: str
    pantry: PantrySpec
    profile: ProfileSeed
    aspect: Aspect
    aligned: tuple[str, ...]  # recipe names that, by hand, honour the signal and are cookable
    derivation: str
    paths: tuple[str, ...]
    request: str = "What should I cook tonight?"
    expected_servings: int | None = None


def _ratings(cuisine: str, stars: int, n: int, start_days_ago: int = 40) -> tuple[MealSeed, ...]:
    return tuple(MealSeed(f"{cuisine} dinner {i}", cuisine, start_days_ago + i, stars) for i in range(n))


def _chicken_week() -> tuple[MealSeed, ...]:
    # Four chicken meals in the last six days: more than max_same_protein_per_week (3) in the 7-day window.
    return tuple(
        MealSeed(
            f"Chicken dinner {i}", None, 1 + i, None, ingredients_used=("chicken breast", "rice", "onion")
        )
        for i in range(4)
    )


_BASE_CASES: list[PersonalizationCase] = [
    PersonalizationCase(
        "d5_01",
        "cuisine preference learned from ratings: Italian loved, Japanese disliked",
        PantrySpec((CARBONARA, SALMON)),
        ProfileSeed(meals=_ratings("Italian", 5, 10) + _ratings("Japanese", 1, 10, 55)),
        Aspect("cuisine", "Italian"),
        ("Spaghetti alla Carbonara",),
        "Pair P1 ties at 0.825 by default. Profile: 10 five-star Italian ratings -> 0.885, 10 one-star Japanese -> 0.115 "
        "(data_points 10 and 10). Cuisine term 0.15*score: Carbonara 0.6 + 0.15*0.885 + 0.15 = 0.883; Salmon 0.6 + 0.15*0.115 + 0.15 = "
        "0.767. Carbonara should be recommended.",
        ("cuisine",),
    ),
    PersonalizationCase(
        "d5_02",
        "the same pair with the OPPOSITE profile: Japanese loved, Italian disliked",
        PantrySpec((CARBONARA, SALMON)),
        ProfileSeed(meals=_ratings("Japanese", 5, 10) + _ratings("Italian", 1, 10, 55)),
        Aspect("cuisine", "Japanese"),
        ("Honey Teriyaki Salmon",),
        "Same pantry as d5_01, profile reversed (10 and 10 ratings). Salmon 0.883 against Carbonara 0.767: the recommendation "
        "must FLIP. A system that ignores the profile cannot pass both d5_01 and d5_02.",
        ("cuisine", "opposite_pair"),
    ),
    PersonalizationCase(
        "d5_03",
        "one rating must not outweigh ten: 10 Italian five-stars vs a single Japanese five-star",
        PantrySpec((CARBONARA, SALMON)),
        ProfileSeed(meals=_ratings("Italian", 5, 10) + _ratings("Japanese", 5, 1, 55)),
        Aspect("cuisine", "Italian"),
        ("Spaghetti alla Carbonara",),
        "data_points: Italian 10 (score 0.885), Japanese 1 (score 0.625 after shrinking toward neutral). Both are positive but "
        "the confident one is larger: Carbonara 0.883 vs Salmon 0.6 + 0.15*0.625 + 0.15 = 0.844. Carbonara should win; the single "
        "rating must not dominate.",
        ("cuisine", "confidence"),
    ),
    PersonalizationCase(
        "d5_04",
        "disliked ingredient in the recipe the default scoring would pick",
        PantrySpec((CARBONARA, ENCHILADA)),
        ProfileSeed(disliked_ingredients=("bacon",)),
        Aspect("dislike", "bacon"),
        ("Chicken Enchilada Casserole",),
        "Pair P2: with no profile Carbonara leads (0.825 vs 0.675) because of the cook-time nudge. Carbonara contains bacon, which "
        "the user dislikes; Enchilada does not. The dislike should override the nudge: Enchilada.",
        ("dislike",),
    ),
    PersonalizationCase(
        "d5_05",
        "disliked main ingredient: salmon",
        PantrySpec((SALMON, ENCHILADA)),
        ProfileSeed(disliked_ingredients=("salmon",)),
        Aspect("dislike", "salmon"),
        ("Chicken Enchilada Casserole",),
        "Pair P3: Salmon leads by default (0.825 vs 0.675) and is the disliked ingredient itself. Expected: Enchilada.",
        ("dislike",),
    ),
    PersonalizationCase(
        "d5_06",
        "disliked ingredient: cream",
        PantrySpec((FETTUCINE, MBUZI)),
        ProfileSeed(disliked_ingredients=("cream",)),
        Aspect("dislike", "cream"),
        ("Mbuzi Choma (Roasted Goat)",),
        "Pair P4: Fettucine alfredo (4 min, Clotted Cream) leads by default; the user dislikes cream. Mbuzi Choma has none. "
        "Expected: Mbuzi Choma.",
        ("dislike",),
    ),
    PersonalizationCase(
        "d5_07",
        "protein preference (profile): chicken",
        PantrySpec((ENCHILADA, BAKED_SALMON)),
        ProfileSeed(protein_preference="chicken"),
        Aspect("protein", "chicken"),
        ("Chicken Enchilada Casserole",),
        "Pair P5 ties at 0.675 (both over 30 minutes). A stored protein preference of chicken should add the 0.15 protein term "
        "to the chicken recipe: Enchilada 0.825 vs Baked salmon 0.675.",
        ("protein",),
    ),
    PersonalizationCase(
        "d5_08",
        "protein preference (profile): salmon -- the opposite of d5_07 on the same pantry",
        PantrySpec((ENCHILADA, BAKED_SALMON)),
        ProfileSeed(protein_preference="salmon"),
        Aspect("protein", "salmon"),
        ("Baked salmon with fennel & tomatoes",),
        "Same pantry as d5_07 with the opposite stored preference: Baked salmon 0.825 vs Enchilada 0.675. Must flip.",
        ("protein", "opposite_pair"),
    ),
    PersonalizationCase(
        "d5_09",
        "household size drives servings",
        PantrySpec((BOULANGERE,)),
        ProfileSeed(household_size=4),
        Aspect("household", 4),
        (),
        "Household size 4 is stored; the request states no number of people. Servings should default to 4 and the recommended "
        "recipe should be scaled to 4.",
        ("household",),
        expected_servings=4,
    ),
    PersonalizationCase(
        "d5_10",
        "a stated number of people overrides the stored household size",
        PantrySpec((BOULANGERE,)),
        ProfileSeed(household_size=4),
        Aspect("household", 2),
        (),
        "Household size 4 is stored, but the request says 2 people: what is stated wins. Servings should be 2.",
        ("household", "override"),
        request="What can I cook for 2 people tonight?",
        expected_servings=2,
    ),
    PersonalizationCase(
        "d5_11",
        "preferred cook time (soft default) favours the quick recipe",
        PantrySpec((KUMPIR, CARBONARA)),
        ProfileSeed(preferred_cook_time_minutes=20),
        Aspect("quick", 20),
        ("Spaghetti alla Carbonara",),
        "Pair P6, preferred cook time 20: Carbonara (15 min) fits, Kumpir (25 min) does not. Both are 1.0 matches, so the 0.15 "
        "time-fit nudge applies only to Carbonara: 0.825 vs 0.675. Under the 30-minute DEFAULT both would fit and tie; this case "
        "needs the stored 20 to be honoured.",
        ("cook_time",),
    ),
    PersonalizationCase(
        "d5_12",
        "preferred cook time is a default, not a limit: only slow recipes are possible",
        PantrySpec((BOULANGERE,)),
        ProfileSeed(preferred_cook_time_minutes=20),
        Aspect("soft_time", 20),
        (),
        "Preferred cook time 20, but the only cookable recipes take longer (Boulangere 60 min). A preference must RANK, not exclude: "
        "the system should still recommend a cookable recipe, not refuse.",
        ("cook_time", "soft_default"),
    ),
    PersonalizationCase(
        "d5_13",
        "repetition: the recipe cooked yesterday should not be recommended again (Carbonara)",
        PantrySpec((CARBONARA, SALMON)),
        ProfileSeed(meals=(MealSeed("Spaghetti alla Carbonara", "Italian", 1, None, recipe_id=CARBONARA),)),
        Aspect("repeat_recipe", CARBONARA),
        ("Honey Teriyaki Salmon",),
        "Pair P1 ties at 0.825. Carbonara was cooked 1 day ago (exact repeat, repetition score 1.0, penalty 0.10): 0.725 vs Salmon "
        "0.825. Expected: Salmon.",
        ("repetition",),
    ),
    PersonalizationCase(
        "d5_14",
        "repetition, opposite: the Salmon was cooked yesterday",
        PantrySpec((CARBONARA, SALMON)),
        ProfileSeed(meals=(MealSeed("Honey Teriyaki Salmon", "Japanese", 1, None, recipe_id=SALMON),)),
        Aspect("repeat_recipe", SALMON),
        ("Spaghetti alla Carbonara",),
        "Same pantry, mirror history: Salmon 0.725 vs Carbonara 0.825. Expected: Carbonara. Must flip with d5_13.",
        ("repetition", "opposite_pair"),
    ),
    PersonalizationCase(
        "d5_15",
        "protein repetition: four chicken meals this week",
        PantrySpec((ENCHILADA, BAKED_SALMON)),
        ProfileSeed(meals=_chicken_week()),
        Aspect("repeat_protein", "chicken"),
        ("Baked salmon with fennel & tomatoes",),
        "Pair P5 ties at 0.675. Four chicken meals in the last 6 days exceed the weekly limit (3), so the chicken recipe takes a "
        "protein-repetition score of 0.7 (penalty 0.07): Enchilada 0.605 vs Baked salmon 0.675. Expected: Baked salmon.",
        ("repetition", "protein"),
    ),
]

assert len(_BASE_CASES) == 15

# Added AFTER the first Dimension 5 runs (run_1793997836 and run_1793999325, 2026-11-06), which found that
# restrictions SAVED on the profile were stored correctly and never applied (a probe with a saved
# "vegetarian" got a salmon dish). The original 15 are unchanged and keep their ids; three cases were added,
# and the dimension is now 18 cases against the same 0.80 threshold. Each was designed before being run:
#   d5_16  saved vegetarian (tag-backed path): default scoring would pick Carbonara or Salmon.
#   d5_17  saved peanut-free (ingredient-enforced path): default scoring would pick Peanut Butter Cookies.
#   d5_18  a saved dislike with NO cookable alternative: the system must still recommend, not refuse.
_ADDED_AFTER_PROFILE_FIX: list[PersonalizationCase] = [
    PersonalizationCase(
        "d5_16",
        "SAFETY: a saved vegetarian restriction is honoured with nothing stated in the request",
        PantrySpec((CARBONARA, SALMON, BOULANGERE)),
        ProfileSeed(dietary_restrictions=("vegetarian",)),
        Aspect("restriction", "vegetarian"),
        ("Boulangère Potatoes",),
        "Pantry: Carbonara (bacon), Teriyaki Salmon and Boulangere Potatoes. Default scoring picks Carbonara or Salmon "
        "(0.825) over Boulangere (0.675), neither of which is vegetarian. The profile saves 'vegetarian' and the request "
        "says nothing: only Boulangere is permitted. A saved restriction must behave exactly like a stated one.",
        ("restriction", "profile_safety"),
    ),
    PersonalizationCase(
        "d5_17",
        "SAFETY: a saved peanut-free restriction (no corpus tag; enforced on ingredients)",
        PantrySpec(("52958", BOULANGERE)),
        ProfileSeed(dietary_restrictions=("peanut-free",)),
        Aspect("restriction", "peanut_free"),
        ("Boulangère Potatoes",),
        "Pantry: Peanut Butter Cookies (peanut butter, sugar, egg; 9 min) and Boulangere Potatoes. Default scoring picks the "
        "cookies (0.825 vs 0.675); they contain peanut butter. A saved 'peanut-free' has no corpus tag, so it must be "
        "enforced through the ingredient rules. Expected: Boulangere.",
        ("restriction", "profile_safety", "ingredient_enforced"),
    ),
    PersonalizationCase(
        "d5_18",
        "a saved dislike is not an allergy: with no alternative, recommend anyway",
        PantrySpec((CARBONARA,)),
        ProfileSeed(disliked_ingredients=("bacon",)),
        Aspect("dislike_fallback", "bacon"),
        (),
        "The pantry makes exactly one recipe, Carbonara, which contains the disliked bacon. A dislike must not leave the user "
        "with nothing: the system should still recommend it (and say it contains bacon), not refuse.",
        ("dislike", "fallback"),
    ),
]

PERSONALIZATION_CASES: list[PersonalizationCase] = _BASE_CASES + _ADDED_AFTER_PROFILE_FIX

assert len(PERSONALIZATION_CASES) == 18
assert len({c.case_id for c in PERSONALIZATION_CASES}) == 18
