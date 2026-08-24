"""Extracts the distinct ingredient names the vision model actually
produced across scripts/benchmark_vision.py's checkpointed runs, so
nutrition coverage can be measured against real vision-model vocabulary,
not just against TheMealDB's recipe text.

Phase 2.2 verification found that the earlier "100% coverage" figure only
ever measured coverage over ingredient strings appearing in the seeded
recipe corpus. The vision layer produces its own vocabulary ("white
rice", "chicken thigh", "scallions") that never appears in TheMealDB at
all, so that figure said nothing about whether a photo-derived ingredient
list would actually find its nutrition data. This module closes that
measurement gap by parsing the same raw, checkpointed vision outputs the
benchmark itself produced.

The checkpoint file (backend/.cache/vision_benchmark_checkpoint.jsonl,
gitignored, produced by actually running scripts/benchmark_vision.py) is
not committed to the repo, so nothing here assumes it exists — callers
should treat a missing checkpoint as "nothing to check yet," not an
error.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

# mealsight/seed/vision_vocabulary.py -> mealsight/seed -> mealsight -> backend -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
VISION_BENCHMARK_CHECKPOINT_PATH = REPO_ROOT / ".cache" / "vision_benchmark_checkpoint.jsonl"

_NUMBERED_LINE_RE = re.compile(r"^\s*\d+[.):]?\s*")
_BRACKETED_ITEM_RE = re.compile(r"^<([^>]+)>")
_PAREN_RE = re.compile(r"\([^)]*\)")
_PREAMBLE_PREFIXES = (
    "here is", "here are", "the image shows", "based on",
    "i can see", "i clearly see", "looking at",
)


def _clean_line(raw_line: str) -> str | None:
    """Turns one raw line of a vision model's response into a bare
    ingredient-name guess, or None if the line isn't one at all (a
    preamble/closing sentence rather than a list item).

    Handles every shape actually observed across the benchmark's prompt
    variants: plain numbered lines ("1. Sweet potatoes"), bare lines with
    a trailing confidence/location annotation ("Bananas | confidence:
    high"), and bracketed items with annotations ("<Bananas> |
    confidence: high | location: ..."). Parenthetical asides ("(on the
    middle shelf)", "(or fingerling potatoes)") are stripped as
    descriptive noise, not part of the ingredient's identity.
    """
    raw_line = raw_line.strip()
    if not raw_line:
        return None
    lowered = raw_line.lower()
    if lowered.startswith(_PREAMBLE_PREFIXES) or lowered.rstrip().endswith(":"):
        return None

    cleaned = _NUMBERED_LINE_RE.sub("", raw_line).strip()
    if not cleaned:
        return None

    bracket_match = _BRACKETED_ITEM_RE.match(cleaned)
    name = bracket_match.group(1) if bracket_match else cleaned.split("|")[0]
    name = _PAREN_RE.sub("", name).strip().rstrip(".").strip()
    return name or None


def extract_vision_ingredient_names(checkpoint_path: Path = VISION_BENCHMARK_CHECKPOINT_PATH) -> Counter[str]:
    """Parses every checkpointed vision response and returns a Counter of
    raw (not yet normalized) ingredient-name guesses to how many times
    each one was actually produced across every model/prompt/photo/rep
    combination in the checkpoint — the same "how common is this" weight
    mealsight.seed.load_nutrition's recipe-corpus coverage report uses.

    Returns an empty Counter if the checkpoint file doesn't exist —
    callers should treat that as "nothing to check yet", not an error.
    """
    if not checkpoint_path.exists():
        return Counter()

    counter: Counter[str] = Counter()
    for raw_record_line in checkpoint_path.read_text().splitlines():
        if not raw_record_line.strip():
            continue
        record = json.loads(raw_record_line)
        text = record.get("text") or ""
        for raw_line in text.splitlines():
            name = _clean_line(raw_line)
            if name:
                counter[name] += 1
    return counter
