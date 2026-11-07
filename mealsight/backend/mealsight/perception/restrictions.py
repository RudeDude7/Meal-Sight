"""A deterministic backstop for dietary restrictions.

Measured (see backend/eval/README.md): the extraction model sometimes files
"nut-free" under avoid_ingredients instead of dietary_restrictions, and
which it picks varies between near-identical sentences. This reads the
user's own words with fixed patterns and returns the restrictions they
literally state, so the final list is the UNION of the model's answer and
this one. A restriction the user said can then never be lost to the model's
field choice.

Scope, stated plainly: every restriction in the extraction vocabulary that a
user is likely to say by name, and only phrasings the patterns cover. A
paraphrase outside them ("my son can't have almonds") is still the model's
job, and is additionally caught by the avoid-list filter. Over-restricting is
the safe direction, so the one deliberate gap is the other way: when the
utterance contains a self-correction cue ("oh wait", "actually", "never mind",
"is fine"), the backstop stands down rather than re-adding a restriction the
speaker may just have retracted.
"""

from __future__ import annotations

import re


def _free_of(word: str) -> str:
    """Phrasings that state an exclusion of `word` (peanut, shellfish, soy, egg ...)."""
    return (
        rf"\b{word}[\s-]?free\b|\b(?:no|without|nothing\s+with)\s+{word}s?\b"
        rf"|\b{word}s?\s+allerg\w+|\ballergic\s+to\s+{word}s?\b"
    )


_PATTERNS: dict[str, re.Pattern[str]] = {
    # Tag-backed (the corpus carries these as tags).
    "vegan": re.compile(r"\bvegan\b"),
    "vegetarian": re.compile(r"\bvegetarian\b"),
    "gluten-free": re.compile(r"\bgluten[\s-]?free\b|\b(?:no|without)\s+gluten\b"),
    "dairy-free": re.compile(r"\bdairy[\s-]?free\b|\blactose[\s-]?free\b|\b(?:no|without)\s+dairy\b"),
    "nut-free": re.compile(
        r"\b(?:tree[\s-]?)?nut[\s-]?free\b|\b(?:no|without|nothing\s+with)\s+(?:tree\s+)?nuts?\b"
        r"|\b(?:tree\s+)?nuts?\s+allerg\w+|\ballergic\s+to\s+(?:tree\s+)?nuts?\b"
    ),
    # Enforced against ingredient lists (mealsight.matching.diet).
    "peanut-free": re.compile(_free_of("peanut")),
    "shellfish-free": re.compile(_free_of("shellfish")),
    "soy-free": re.compile(_free_of("soy")),
    "egg-free": re.compile(_free_of("egg")),
    "pescatarian": re.compile(r"\bpesc[ae]tarian\b"),
    "halal": re.compile(r"\bhalal\b"),
    "kosher": re.compile(r"\bkosher\b"),
    # Nutrition-based or unenforced: detected so they are enforced or DISCLOSED, never lost.
    "low-carb": re.compile(r"\blow[\s-]?carb(?:ohydrate)?s?\b"),
    "keto": re.compile(r"\bketo(?:genic)?\b"),
    "low-sodium": re.compile(r"\blow[\s-]?(?:sodium|salt)\b"),
    "low-fat": re.compile(r"\blow[\s-]?fat\b"),
    "paleo": re.compile(r"\bpaleo\b"),
}
# "I have no eggs" / "got no peanuts" describes the pantry, not a restriction.
_POSSESSION = re.compile(r"(?:\bhave|\bhad|\bgot|\bhaven't)\s+(?:\w+\s+){0,1}$")
_NEGATED = re.compile(r"(?:\bnot|n't|\bnon|\bnever)[\s-]+(?:\w+\s+){0,2}$")
_SELF_CORRECTION = re.compile(
    r"\boh wait\b|\bactually\b|\bnever ?mind\b|\bscratch that\b|\bon second thought\b"
    r"|\b(?:is|are|that's|it's)\s+(?:fine|ok|okay)\b|\bi mean\b"
)


def detect_dietary_restrictions(utterance: str) -> list[str]:
    text = utterance.lower().replace("’", "'")
    if _SELF_CORRECTION.search(text):
        return []
    found: list[str] = []
    for restriction, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            before = text[: match.start()]
            has_no_cue = match.group(0).startswith("no ")
            if _NEGATED.search(before) or (has_no_cue and _POSSESSION.search(before)):
                continue
            found.append(restriction)
            break
    return found
