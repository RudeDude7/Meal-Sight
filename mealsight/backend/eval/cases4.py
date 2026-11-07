# ruff: noqa: E501  (hand-written derivation prose)
"""Dimension 4's 15 freshness-prioritization cases.

THE QUESTION. When an ingredient is near expiry, does the recommendation actually use it?

WHAT COUNTS AS A FAILURE. A recommendation cannot use an expiring item that no cookable
recipe uses, so that is never a failure. Each case is judged against the set of recipes that
were actually possible: eval/analysis.py runs the matcher (whose arithmetic Dimension 3
verified) over the WHOLE corpus for the case's pantry, and finds the cookable recipes that use
an expiring, usable item (set U). Then, for the recommended recipe R:

  no_opportunity            U is empty. Pass: there was nothing to prioritize.
  used                      R is in U. Pass.
  justified_deprioritization R is not in U but its hand-computed composite beats every recipe in U.
                            Pass: a far better recipe correctly beat a marginal one that uses
                            the item. The freshness bonus is one term among several (0.15 against
                            0.60 for ingredient match), so a match advantage of more than 0.25
                            outweighs it.
  failed_to_prioritize      R is not in U, and some recipe in U scored at least as well as R by the
                            hand composite. Fail. (A refusal while U is non-empty also fails.)

EXPECTED OUTCOMES. Each case states, from its pantry design alone, what the situation is
(`expected_situation`), which items should be reported as expiring opportunities and which
as waste. These were written before any run, from the rules: a usable item is one with
days_remaining <= 3 that is not more than 2 days past its shelf life (settings.expiring_soon_days,
expired_grace_days); an item further past it is waste and is excluded from matching entirely. The
harness then checks the situation it computes against `expected_situation`: if they differ, the
CASE is mis-designed and is reported as a case defect, not as a system failure.

A second, separate measure checks the mechanism itself: for every ranked candidate, whether the
freshness flag match_rank set agrees with an independent computation of "this recipe uses an
expiring item".
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.isolation import PantrySeed

REQUEST = "What should I cook tonight?"  # no constraints: the pantry alone decides the situation

# Staples that never expire. They make a number of baking recipes cookable, which is deliberate: it
# gives the system real alternatives to choose between.
STAPLES = [
    PantrySeed("salt"),
    PantrySeed("black pepper"),
    PantrySeed("olive oil"),
    PantrySeed("vegetable oil"),
    PantrySeed("butter"),
    PantrySeed("all purpose flour"),
    PantrySeed("sugar"),
]

# Ingredient sets of small recipes, so a pantry can be built to make exactly them cookable.
BOULANGERE = ["onion", "thyme", "potato", "vegetable stock"]  # + olive oil (staple): Boulangere Potatoes, 5/5
PANCAKES = ["egg", "milk", "raspberry", "blueberry", "sunflower oil"]  # + flour, sugar: Pancakes
KARAAGE = ["ginger", "garlic", "soy sauce", "lemon"]  # + chicken (thigh): Chicken Karaage 6/9


def _pantry(
    *groups: list[str], expiring: dict[str, int] | None = None, fresh_extra: list[str] | None = None
) -> tuple[PantrySeed, ...]:
    """A pantry: the staples, plus each group's items, with `expiring` giving days_remaining for any
    item (a staple included: an expiring entry REPLACES the never-expiring staple)."""
    expiring = expiring or {}
    items: dict[str, PantrySeed] = {s.name: s for s in STAPLES}
    for g in groups:
        for n in g:
            items.setdefault(n, PantrySeed(n, expiring.get(n)))
    for n in fresh_extra or []:
        items.setdefault(n, PantrySeed(n, expiring.get(n)))
    for n, d in expiring.items():
        items[n] = PantrySeed(n, d)
    return tuple(items.values())


@dataclass(frozen=True)
class FreshnessCase:
    case_id: str
    description: str
    pantry: tuple[PantrySeed, ...]
    expected_situation: str  # "must_prioritize" | "no_opportunity" | "justified_deprioritization"
    expected_expiring: tuple[str, ...]  # usable items that should be reported as expiring opportunities
    expected_waste: tuple[str, ...]  # items too far past shelf life: waste, never an opportunity
    derivation: str
    paths: tuple[str, ...]
    request: str = REQUEST


FRESHNESS_CASES: list[FreshnessCase] = [
    FreshnessCase(
        "d4_01",
        "one item expiring tomorrow, one recipe built on it",
        _pantry(BOULANGERE, expiring={"thyme": 1}),
        "must_prioritize",
        ("thyme",),
        (),
        "Thyme has 1 day left, so it is an opportunity. Boulangere Potatoes (onion, thyme, olive oil, potato, vegetable stock) is "
        "fully cookable and uses it: match 1.0. Every other recipe the pantry can make is a weaker match (0.5-0.6) that does not "
        "use thyme, so the expiring-item recipe is also the best overall. It should be recommended.",
        ("basic",),
    ),
    FreshnessCase(
        "d4_02",
        "perishable dairy expiring, many recipes use it",
        _pantry(PANCAKES, expiring={"milk": 1}),
        "must_prioritize",
        ("milk",),
        (),
        "Milk (1 day) is used by Pancakes (match 1.0) and by a dozen other baking recipes the staples make cookable. Whichever "
        "is chosen, the recommendation should be one of the milk recipes.",
        ("many_users",),
    ),
    FreshnessCase(
        "d4_03",
        "two different items expiring, used by different recipes",
        _pantry(BOULANGERE, PANCAKES, expiring={"thyme": 1, "milk": 2}),
        "must_prioritize",
        ("thyme", "milk"),
        (),
        "Thyme (1 day) is used by Boulangere Potatoes and milk (2 days) by Pancakes and others. Using EITHER satisfies the "
        "goal; the recommendation should use at least one.",
        ("multiple_expiring",),
    ),
    FreshnessCase(
        "d4_04",
        "expiring item that no recipe uses",
        _pantry(["onion", "potato", "cheese"], expiring={"kiwi": 1}),
        "no_opportunity",
        ("kiwi",),
        (),
        "A kiwi has 1 day left but no recipe in the corpus calls for kiwi, so no cookable recipe can use it. This is not a "
        "failure: nothing should be penalized for ignoring it.",
        ("no_opportunity",),
    ),
    FreshnessCase(
        "d4_05",
        "item 5 days past its shelf life is waste, not an opportunity",
        _pantry(BOULANGERE, expiring={"thyme": -5}),
        "no_opportunity",
        (),
        ("thyme",),
        "Thyme at -5 days is beyond the 2-day grace, so it is waste: it must not be reported as an expiring opportunity and it is "
        "excluded from matching entirely. With no usable expiring item there is no opportunity. (Boulangere Potatoes still cooks "
        "at 4/5 = 0.8 without the thyme, but must not claim to use it.)",
        ("expired_excluded",),
    ),
    FreshnessCase(
        "d4_06",
        "grace boundary: 2 days past is still usable, 3 days past is waste",
        _pantry(BOULANGERE, expiring={"thyme": -2, "vegetable stock": -3}),
        "must_prioritize",
        ("thyme",),
        ("vegetable stock",),
        "Thyme at -2 is inside the grace window (days < -2 is waste), so it is still an opportunity; vegetable stock at -3 is "
        "outside it and is waste. Boulangere Potatoes (onion, thyme, olive oil, potato = 4/5 = 0.8) is cookable and uses the thyme.",
        ("expired_excluded", "boundary"),
    ),
    FreshnessCase(
        "d4_07",
        "a marginal recipe uses the expiring item; a far better recipe exists",
        _pantry(BOULANGERE, expiring={"cabbage": 1}),
        "justified_deprioritization",
        ("cabbage",),
        (),
        "Cabbage (1 day) is used only by Corned Beef and Cabbage and Golabki, each a 0.5 match (cookable, but barely). "
        "Boulangere Potatoes is a 1.0 match. Composite: Boulangere 0.60*1.0 + 0.075 = 0.675; the cabbage recipe 0.60*0.5 + 0.15 + "
        "0.075 = 0.525. The better recipe is the correct recommendation, so choosing it must PASS.",
        ("justified_deprioritization",),
    ),
    FreshnessCase(
        "d4_08",
        "expiring chicken THIGH; the recipe line says just 'chicken'",
        _pantry(KARAAGE, expiring={"chicken thigh": 1}),
        "must_prioritize",
        ("chicken thigh",),
        (),
        "Chicken Karaage wants 'chicken'; a chicken thigh is a more specific cut and satisfies it fully (Dimension 3, d3_03). So "
        "the thigh IS used by Karaage (6/9 = 0.667, cookable) and the freshness bonus should apply. Tests that the bonus survives "
        "a specificity match, where the recipe's name and the pantry item's name differ.",
        ("specificity", "mechanism"),
    ),
    FreshnessCase(
        "d4_09",
        "expiring chicken",
        _pantry(["onion", "potato", "tomato"], expiring={"chicken": 1}),
        "must_prioritize",
        ("chicken",),
        (),
        "Chicken (1 day) is used by any chicken recipe the pantry can support; the recommendation should be one of them.",
        ("basic",),
    ),
    FreshnessCase(
        "d4_10",
        "nothing near expiry (control)",
        _pantry(BOULANGERE, ["cheese"]),
        "no_opportunity",
        (),
        (),
        "Every item has a year of shelf life: nothing is expiring, so no opportunity exists and the expiring list must be empty.",
        ("control",),
    ),
    FreshnessCase(
        "d4_11",
        "threshold edge: 3 days left counts, 4 days left does not",
        _pantry(BOULANGERE, ["cheese"], expiring={"thyme": 3, "cheese": 4}),
        "must_prioritize",
        ("thyme",),
        (),
        "expiring_soon_days is 3: thyme with 3 days left is an opportunity, cheese with 4 is not (so Kumpir gets no bonus for it). "
        "Boulangere Potatoes uses the thyme and is a 1.0 match.",
        ("boundary",),
    ),
    FreshnessCase(
        "d4_12",
        "expiring item whose only recipe cannot be cooked",
        _pantry(["onion", "potato"], expiring={"salmon": 1}),
        "no_opportunity",
        ("salmon",),
        (),
        "Salmon (1 day) is the critical ingredient of Honey Teriyaki Salmon, but the pantry has only salmon and olive oil of its five "
        "ingredients (2/5 = 0.4, below 0.5), so it is not cookable. An uncookable recipe must not be pushed just because it uses "
        "the expiring item: there is no cookable opportunity.",
        ("uncookable_user",),
    ),
    FreshnessCase(
        "d4_13",
        "expiring staple used by nearly every baking recipe",
        _pantry(PANCAKES, expiring={"butter": 1}),
        "must_prioritize",
        ("butter",),
        (),
        "Butter (1 day) is used by most of the baking recipes this pantry supports; the recommendation should be one of them.",
        ("many_users",),
    ),
    FreshnessCase(
        "d4_14",
        "expiring vegetable that several savoury recipes use",
        _pantry(BOULANGERE, ["cheese"], expiring={"potato": 2}),
        "must_prioritize",
        ("potato",),
        (),
        "Potato (2 days) is used by Boulangere Potatoes (1.0) and Kumpir among others.",
        ("basic",),
    ),
    FreshnessCase(
        "d4_15",
        "second marginal user: lemon expiring, only a weak recipe uses it",
        _pantry(BOULANGERE, expiring={"lemon": 1}),
        "justified_deprioritization",
        ("lemon",),
        (),
        "Lemon (1 day) is used only by weak matches (Skillet Apple Pork Chops at 0.5, cookable but barely) while Boulangere "
        "Potatoes is a 1.0 match: 0.675 against 0.525. Choosing Boulangere is correct deprioritization and must PASS.",
        ("justified_deprioritization",),
    ),
]

assert len(FRESHNESS_CASES) == 15
assert len({c.case_id for c in FRESHNESS_CASES}) == 15
