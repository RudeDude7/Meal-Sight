"""Dimension 1's own scoring logic — extracted, not rewritten, from
scripts/benchmark_vision.py (the exploratory 3-model x 3-prompt x
5-image x 3-rep benchmark that established the current F1 0.64
baseline for mistral-medium-2505 + the conservative prompt). Every
function below is the identical matcher that benchmark script already
validated: container-word stripping, a curated synonym/brand map,
head-noun containment for compatible adjective modifiers only, and
greedy most-specific-first bipartite assignment. Only the parts tied to
that script's own CallRecord/checkpointing/rate-limiting machinery were
left behind — this module owns just the comparison itself.

Ground truth: test_data/eval_cases/image_ground_truth.csv (30 photos).
Visibility adjustment: test_data/eval_cases/visibility_exclusions.csv —
items confirmed not actually visible in frame, excluded from the
DENOMINATOR of recall_adjusted (never from predicted_items, and never
from raw recall) so a model isn't penalized for failing to see
something nobody could have seen.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH_CSV = REPO_ROOT / "test_data" / "eval_cases" / "image_ground_truth.csv"
VISIBILITY_EXCLUSIONS_CSV = REPO_ROOT / "test_data" / "eval_cases" / "visibility_exclusions.csv"
IMAGES_DIR = REPO_ROOT / "test_data" / "images"

PUNCTUATION_RE = re.compile(r"[^\w\s]")
# A parenthetical is a qualifier ("potatoes (peeled)", "milk (carton labeled
# ...)"), never part of the item's identity — stripped before matching. An
# unclosed "(" (the model truncated the closing paren) strips to end of string.
PARENTHETICAL_RE = re.compile(r"\([^)]*(?:\)|$)")

CONTAINER_WORDS = frozenset(
    {
        "carton",
        "jar",
        "bottle",
        "container",
        "tub",
        "packet",
        "package",
        "packaged",
        "bag",
        "box",
        "can",
        "canned",
        "of",
        "a",
    }
)

COMPATIBLE_MODIFIERS = frozenset(
    {
        "red",
        "green",
        "yellow",
        "orange",
        "white",
        "black",
        "purple",
        "pink",
        "fresh",
        "raw",
        "cooked",
        "ripe",
        "unripe",
        "organic",
        "whole",
        "large",
        "small",
        "medium",
        "big",
        "little",
        "baby",
        "chopped",
        "sliced",
        "diced",
        "minced",
        "ground",
        "shredded",
        "grated",
        "boneless",
        "skinless",
        "bonein",
        "frozen",
        "dried",
    }
)

# Full-phrase equivalences: the container-stripped phrase must equal the
# key exactly — deliberately not substring-based (see benchmark_vision.
# py's own comment: "cream" alone means heavy cream, but "cream cheese"
# is a different food entirely).
SYNONYM_MAP: dict[str, str] = {
    "half and half": "heavy cream",
    "half half": "heavy cream",
    "whipping cream": "heavy cream",
    "cream": "heavy cream",
    "granulated sugar": "sugar",
    "margarine": "butter",
    "butter spread": "butter",
}

BRAND_SYNONYMS: dict[str, str] = {
    "chavroux": "goat cheese",
}

GENERIC_PROTEIN_MAP: dict[str, frozenset[str]] = {
    "meat": frozenset({"beef", "ham", "chicken"}),
}

DISTINCT_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"sweet potato", "potato"}),
        # A scallion is not a bulb onion: the recipe matcher treats them as
        # different pantry items too, so crediting one for the other would
        # score a recognition the pantry could not use.
        frozenset({"green onion", "onion"}),
    }
)


def singularize(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith(("shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("oes") and len(word) > 3:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def normalize_words(phrase: str, strip_qualifiers: bool = True) -> list[str]:
    lowered = phrase.lower()
    text = (PARENTHETICAL_RE.sub(" ", lowered) if strip_qualifiers else lowered).replace("-", " ")
    text = PUNCTUATION_RE.sub("", text)
    return [singularize(w) for w in text.split() if w]


def strip_containers(words: list[str]) -> list[str]:
    return [w for w in words if w not in CONTAINER_WORDS]


def normalize_phrase(phrase: str) -> str:
    return " ".join(strip_containers(normalize_words(phrase)))


def canonical_forms(raw: str) -> set[str]:
    words = strip_containers(normalize_words(raw))
    literal = " ".join(words)
    forms = {literal}

    if literal in SYNONYM_MAP:
        forms.add(SYNONYM_MAP[literal])

    # Brand names are matched against the phrase WITH its parentheticals:
    # "Butter (Chavroux brand)" carries the brand only inside the parens,
    # which the literal reading above deliberately drops.
    brand_words = strip_containers(normalize_words(raw, strip_qualifiers=False))
    n = len(brand_words)
    for key, canon in BRAND_SYNONYMS.items():
        key_words = tuple(key.split())
        k = len(key_words)
        if k == 0 or k > n:
            continue
        for start in range(n - k + 1):
            if tuple(brand_words[start : start + k]) == key_words:
                forms.add(canon)
                break

    return forms


def containment_match(a: str, b: str) -> bool:
    a_words = tuple(a.split())
    b_words = tuple(b.split())
    if not a_words or not b_words or a_words == b_words:
        return False
    shorter, longer = (a_words, b_words) if len(a_words) < len(b_words) else (b_words, a_words)

    if longer[-len(shorter) :] == shorter:
        extra = longer[: -len(shorter)]
    elif longer[: len(shorter)] == shorter:
        extra = longer[len(shorter) :]
    else:
        return False
    return bool(extra) and all(w in COMPATIBLE_MODIFIERS for w in extra)


def match_phrases(a_raw: str, b_raw: str) -> bool:
    a_forms = canonical_forms(a_raw)
    b_forms = canonical_forms(b_raw)

    for af in a_forms:
        for bf in b_forms:
            if frozenset({af, bf}) in DISTINCT_PAIRS:
                return False

    if a_forms & b_forms:
        return True

    for af in a_forms:
        candidates = GENERIC_PROTEIN_MAP.get(af)
        if candidates and (b_forms & candidates):
            return True
    for bf in b_forms:
        candidates = GENERIC_PROTEIN_MAP.get(bf)
        if candidates and (a_forms & candidates):
            return True

    for af in a_forms:
        for bf in b_forms:
            if containment_match(af, bf):
                return True
    return False


def assign_matches(predicted: list[str], ground_truth: list[str]) -> tuple[set[int], set[int]]:
    """Greedy bipartite assignment, most-specific ground-truth term
    first (by word count), so e.g. "sweet potato" claims a matching
    predicted item before the more general "potato" gets a chance at
    it, and each predicted item satisfies at most one ground-truth
    item."""
    matched_predicted: set[int] = set()
    matched_truth: set[int] = set()

    truth_order = sorted(
        range(len(ground_truth)), key=lambda i: -len(normalize_phrase(ground_truth[i]).split())
    )
    for ti in truth_order:
        for pi, predicted_item in enumerate(predicted):
            if pi in matched_predicted:
                continue
            if match_phrases(predicted_item, ground_truth[ti]):
                matched_predicted.add(pi)
                matched_truth.add(ti)
                break

    return matched_predicted, matched_truth


@lru_cache(maxsize=1)
def load_ground_truth_all() -> dict[str, list[str]]:
    by_photo: dict[str, list[str]] = {}
    if not GROUND_TRUTH_CSV.exists():
        return by_photo
    with GROUND_TRUTH_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            by_photo.setdefault(row["photo_id"], []).append(row["item_name"])
    return by_photo


def load_ground_truth(photo_id: str) -> list[str]:
    return load_ground_truth_all().get(photo_id, [])


@lru_cache(maxsize=1)
def load_visibility_exclusions() -> frozenset[tuple[str, str]]:
    if not VISIBILITY_EXCLUSIONS_CSV.exists():
        return frozenset()
    with VISIBILITY_EXCLUSIONS_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        return frozenset((row["photo_id"], row["item_name"].strip().lower()) for row in reader)


def f1_score(precision: float, recall: float) -> float:
    return (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0


class ScoredImage:
    """One photo's own scored result — precision/recall/F1, raw and
    visibility-adjusted, plus which predicted/ground-truth items
    actually matched, so a caller can render or debug either."""

    def __init__(
        self,
        photo_id: str,
        predicted_items: list[str],
        ground_truth: list[str],
        matched_predicted: set[int],
        matched_truth: set[int],
    ) -> None:
        self.photo_id = photo_id
        self.predicted_items = predicted_items
        self.ground_truth = ground_truth
        self.matched_predicted = matched_predicted
        self.matched_truth = matched_truth

        exclusions = load_visibility_exclusions()
        adjusted_truth_indices = {
            i for i, item in enumerate(ground_truth) if (photo_id, item.strip().lower()) not in exclusions
        }

        self.precision = len(matched_predicted) / len(predicted_items) if predicted_items else 0.0
        self.recall_raw = len(matched_truth) / len(ground_truth) if ground_truth else 0.0
        self.recall_adjusted = (
            len(matched_truth & adjusted_truth_indices) / len(adjusted_truth_indices)
            if adjusted_truth_indices
            else 0.0
        )
        self.f1_raw = f1_score(self.precision, self.recall_raw)
        self.f1_adjusted = f1_score(self.precision, self.recall_adjusted)


def score_image(photo_id: str, predicted_items: list[str]) -> ScoredImage:
    ground_truth = load_ground_truth(photo_id)
    matched_predicted, matched_truth = assign_matches(predicted_items, ground_truth)
    return ScoredImage(photo_id, predicted_items, ground_truth, matched_predicted, matched_truth)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def synonym_map_dead_entries(hit_counts: Counter[str]) -> list[str]:
    """Every SYNONYM_MAP/BRAND_SYNONYMS key that never fired against
    this run's own data — worth flagging (not failing on), the same way
    benchmark_vision.py's own run already did, so a stale entry doesn't
    go unnoticed indefinitely."""
    return [key for key in {**SYNONYM_MAP, **BRAND_SYNONYMS} if hit_counts[key] == 0]
