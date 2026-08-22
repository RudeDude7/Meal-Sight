#!/usr/bin/env python3
"""Proper multi-sample benchmark of MealSight's vision models, replacing the
single-sample checks in diagnose_vision.py that gave contradictory F1 scores
for the same (model, prompt, image) combination.

Runs every (model, prompt, image) combination 3 times at temperature=0 so we
can report mean/stddev instead of one noisy sample, uses a real token-bucket
rate limiter instead of fixed sleeps, checkpoints every call to disk as it
completes, and scores with a matcher that does proper one-to-one bipartite
assignment (most-specific ground-truth term first) instead of the earlier
independent-per-item lookup, which could double-count or miss things like
"milk carton" failing to match "milk" purely because of the packaging word.

If .cache/vision_benchmark_checkpoint.jsonl already has every (model, prompt,
image, rep) combination on disk, running this script makes zero API calls —
it just re-scores the existing raw outputs with whatever matching logic is
currently in this file. That's the intended way to fix a scoring bug without
re-spending the API budget.

Diagnostic tooling only — no application code.

Run with: uv run --with Pillow scripts/benchmark_vision.py
"""

from __future__ import annotations

import csv
import itertools
import json
import logging
import re
import statistics
import time
import urllib.error
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from diagnose_vision import (
    ENV_PATH,
    GROUND_TRUTH_CSV,
    IMAGES_DIR,
    MISTRAL_CHAT_URL,
    PROMPT_CONSERVATIVE,
    PROMPT_CURRENT,
    PROMPT_GROUNDED,
    REPO_ROOT,
    REQUEST_TIMEOUT_SECONDS,
    build_data_url,
    http_post_json,
    load_env,
    load_ground_truth,
    parse_item_lines,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = REPO_ROOT / ".cache"
CHECKPOINT_PATH = CACHE_DIR / "vision_benchmark_checkpoint.jsonl"
REPORT_PATH = REPO_ROOT / "docs" / "vision_benchmark_report.md"
VISIBILITY_EXCLUSIONS_CSV = REPO_ROOT / "test_data" / "eval_cases" / "visibility_exclusions.csv"

MODELS = ["mistral-medium-2505", "pixtral-12b-latest", "ministral-8b-2512"]
PROMPTS = [
    ("A-current", PROMPT_CURRENT),
    ("B-conservative", PROMPT_CONSERVATIVE),
    ("C-grounded", PROMPT_GROUNDED),
]
PHOTO_IDS = [f"photo_{i:02d}" for i in range(1, 6)]
REPETITIONS = 3
TEMPERATURE = 0.0

MAX_RETRIES = 6
BACKOFF_BASE_SECONDS = 2.0
STDDEV_FLAG_THRESHOLD = 0.10
BAD_GROUND_TRUTH_F1_THRESHOLD = 0.3

# Only mistral-medium-2505's limit was actually specified for this account;
# the other two get the conservative default rather than a guess, since
# getting rate-limited mid-benchmark costs more than going slow.
RATE_LIMITS_RPS: dict[str, float] = {"mistral-medium-2505": 0.42}
DEFAULT_RATE_LIMIT_RPS = 0.42


# --------------------------------------------------------------------------
# Token-bucket rate limiting
# --------------------------------------------------------------------------


class TokenBucket:
    """Classic token bucket: tokens refill continuously at `rate` per second,
    up to `capacity`. acquire() blocks until a token is available rather than
    sleeping a fixed amount, so bursts right after idle time aren't penalized
    but sustained calls are held to the cap."""

    def __init__(self, rate_per_second: float, capacity: float | None = None) -> None:
        self.rate = rate_per_second
        self.capacity = capacity if capacity is not None else max(1.0, rate_per_second)
        self.tokens = self.capacity
        self.last_refill = time.monotonic()

    def acquire(self) -> None:
        while True:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.last_refill = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            wait_seconds = (1.0 - self.tokens) / self.rate
            time.sleep(wait_seconds)


class RateLimiterPool:
    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def acquire(self, model: str) -> None:
        if model not in self._buckets:
            rate = RATE_LIMITS_RPS.get(model, DEFAULT_RATE_LIMIT_RPS)
            self._buckets[model] = TokenBucket(rate)
        self._buckets[model].acquire()


# --------------------------------------------------------------------------
# Calling the API
# --------------------------------------------------------------------------


@dataclass
class CallRecord:
    model: str
    prompt_label: str
    photo_id: str
    rep: int
    text: str | None
    usage: dict[str, int] = field(default_factory=dict)
    latency_seconds: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.text is not None

    def key(self) -> tuple[str, str, str, int]:
        return (self.model, self.prompt_label, self.photo_id, self.rep)

    def to_json(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_label": self.prompt_label,
            "photo_id": self.photo_id,
            "rep": self.rep,
            "text": self.text,
            "usage": self.usage,
            "latency_seconds": self.latency_seconds,
            "error": self.error,
        }

    @staticmethod
    def from_json(payload: dict[str, Any]) -> "CallRecord":
        return CallRecord(
            model=payload["model"],
            prompt_label=payload["prompt_label"],
            photo_id=payload["photo_id"],
            rep=payload["rep"],
            text=payload.get("text"),
            usage=payload.get("usage", {}),
            latency_seconds=payload.get("latency_seconds", 0.0),
            error=payload.get("error"),
        )


def call_model(
    model: str, prompt: str, api_key: str, limiter: RateLimiterPool, image_data_url: str
) -> tuple[str | None, dict[str, int], float, str | None]:
    """Calls one Mistral chat model at temperature=0, retrying on 429 with
    exponential backoff. Returns (text, usage, latency_seconds, error)."""
    body = {
        "model": model,
        "temperature": TEMPERATURE,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    for attempt in range(1, MAX_RETRIES + 1):
        limiter.acquire(model)
        started = time.monotonic()
        try:
            status, response_body, response_headers = http_post_json(MISTRAL_CHAT_URL, headers, body)
        except (urllib.error.URLError, TimeoutError) as exc:
            return None, {}, time.monotonic() - started, f"network error: {exc}"
        latency = time.monotonic() - started

        if status == 429:
            retry_after = response_headers.get("Retry-After")
            delay = float(retry_after) if retry_after else BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning("429 from %s (attempt %d/%d) — backing off %.1fs", model, attempt, MAX_RETRIES, delay)
            time.sleep(delay)
            continue

        if status == 404:
            return None, {}, latency, "HTTP 404 — model does not resolve on this account"

        if status != 200:
            return None, {}, latency, f"HTTP {status}: {response_body[:300]!r}"

        try:
            payload = json.loads(response_body)
            text = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            return None, {}, latency, f"unexpected response shape: {exc}"

        return text, usage, latency, None

    return None, {}, 0.0, f"gave up after {MAX_RETRIES} retries (429)"


# --------------------------------------------------------------------------
# Checkpointing
# --------------------------------------------------------------------------


def load_checkpoint() -> dict[tuple[str, str, str, int], CallRecord]:
    records: dict[tuple[str, str, str, int], CallRecord] = {}
    if not CHECKPOINT_PATH.exists():
        return records
    with CHECKPOINT_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = CallRecord.from_json(json.loads(line))
            records[record.key()] = record
    return records


def append_checkpoint(record: CallRecord) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with CHECKPOINT_PATH.open("a") as f:
        f.write(json.dumps(record.to_json()) + "\n")
        f.flush()


# --------------------------------------------------------------------------
# Matching logic
#
# Three layers, in order of how much we trust them:
#   1. Container/packaging-word stripping — "milk carton" and "milk" are
#      obviously the same food; the packaging noun shouldn't cost a match.
#   2. A curated synonym map for phrasings we've actually seen the models
#      use for a ground-truth term (half-and-half -> heavy cream, etc), plus
#      a small set of brand names that unambiguously identify one food
#      regardless of what the model called it (Chavroux -> goat cheese).
#   3. Head-noun containment for simple adjective modifiers only (red bell
#      pepper == bell pepper), gated by an explicit whitelist so we don't
#      accidentally conflate "sweet potato" with "potato" or "peanut butter"
#      with "butter" — those keep separate identities on purpose.
#
# Every near-miss (predicted and truth items that share a word but didn't
# formally match) gets logged so a human can decide if the matcher or the
# model was wrong, rather than silently discarding the disagreement.
# --------------------------------------------------------------------------

PUNCTUATION_RE = re.compile(r"[^\w\s]")

CONTAINER_WORDS = frozenset(
    {"carton", "jar", "bottle", "container", "tub", "packet", "package", "packaged", "bag", "box", "can", "canned", "of", "a"}
)

COMPATIBLE_MODIFIERS = frozenset(
    {
        "red", "green", "yellow", "orange", "white", "black", "purple", "pink",
        "fresh", "raw", "cooked", "ripe", "unripe", "organic", "whole",
        "large", "small", "medium", "big", "little", "baby",
        "chopped", "sliced", "diced", "minced", "ground", "shredded", "grated",
        "boneless", "skinless", "bonein", "frozen", "dried",
    }
)

# Full-phrase equivalences: the container-stripped phrase must equal the key
# exactly. Deliberately NOT substring-based, because e.g. "cream" alone
# should mean heavy cream, but "cream cheese" is a different food entirely —
# requiring exact equality keeps that distinction intact.
SYNONYM_MAP: dict[str, str] = {
    "half and half": "heavy cream",
    "half half": "heavy cream",
    "whipping cream": "heavy cream",
    "cream": "heavy cream",
    "granulated sugar": "sugar",
    "margarine": "butter",
    "butter spread": "butter",
    # Deliberately NOT mapped anywhere — there's no granola/cereal/muesli
    # ground-truth class in this dataset, so these should stay unmatched
    # hallucinations rather than being papered over.
}

# Brand names are unambiguous identifiers, so unlike SYNONYM_MAP these are
# allowed to fire anywhere they appear as a whole word inside a longer
# descriptive phrase (e.g. "Butter (Chavroux brand)" still means goat
# cheese even though the model's own noun choice was wrong).
BRAND_SYNONYMS: dict[str, str] = {
    "chavroux": "goat cheese",
}

# A generic term that could refer to any of several specific ground-truth
# proteins — allowed to match whichever of those happens to be present and
# still unmatched, but never more than one at a time.
GENERIC_PROTEIN_MAP: dict[str, frozenset[str]] = {
    "meat": frozenset({"beef", "ham", "chicken"}),
}

# Pairs that share words but are NOT the same food — the containment rule
# would otherwise incorrectly merge them.
DISTINCT_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"sweet potato", "potato"}),
    }
)

# Tracks which SYNONYM_MAP / BRAND_SYNONYMS entries actually fired during a
# scoring run, so dead entries can be flagged instead of silently doing
# nothing. Reset at the start of every score_all_calls() run.
_synonym_hit_counts: Counter[str] = Counter()


def reset_synonym_hit_tracking() -> None:
    _synonym_hit_counts.clear()


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


def normalize_words(phrase: str) -> list[str]:
    text = phrase.lower().replace("-", " ")
    text = PUNCTUATION_RE.sub("", text)
    return [singularize(w) for w in text.split() if w]


def strip_containers(words: list[str]) -> list[str]:
    return [w for w in words if w not in CONTAINER_WORDS]


def normalize_phrase(phrase: str) -> str:
    """Container-stripped, singularized, space-joined normal form. Used for
    the word-overlap near-miss check as well as inside canonical_forms."""
    return " ".join(strip_containers(normalize_words(phrase)))


def canonical_forms(raw: str) -> set[str]:
    """All the food identities a phrase could plausibly represent: its own
    literal (container-stripped) reading, plus any synonym/brand hits."""
    words = strip_containers(normalize_words(raw))
    literal = " ".join(words)
    forms = {literal}

    if literal in SYNONYM_MAP:
        canon = SYNONYM_MAP[literal]
        forms.add(canon)
        _synonym_hit_counts[literal] += 1

    n = len(words)
    for key, canon in BRAND_SYNONYMS.items():
        key_words = tuple(key.split())
        k = len(key_words)
        if k == 0 or k > n:
            continue
        for start in range(n - k + 1):
            if tuple(words[start : start + k]) == key_words:
                forms.add(canon)
                _synonym_hit_counts[key] += 1
                break

    return forms


def containment_match(a: str, b: str) -> bool:
    """Head-noun containment for simple adjective modifiers only — the extra
    word(s) on the longer phrase must all be in the compatible-modifier
    whitelist, otherwise we assume the modifier changes the food's identity
    (sweet potato vs potato, peanut butter vs butter, etc)."""
    a_words = tuple(a.split())
    b_words = tuple(b.split())
    if not a_words or not b_words or a_words == b_words:
        return False
    shorter, longer = (a_words, b_words) if len(a_words) < len(b_words) else (b_words, a_words)

    if longer[-len(shorter):] == shorter:
        extra = longer[: -len(shorter)]
    elif longer[: len(shorter)] == shorter:
        extra = longer[len(shorter):]
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
    """Greedy bipartite assignment, most-specific ground-truth term first
    (by word count), so e.g. 'sweet potato' claims a matching predicted item
    before the more general 'potato' gets a chance at it — and each
    predicted item can only satisfy one ground-truth item, so a single
    generic 'meat' can't double-count against both beef and ham."""
    matched_predicted: set[int] = set()
    matched_truth: set[int] = set()

    truth_order = sorted(range(len(ground_truth)), key=lambda i: -len(normalize_phrase(ground_truth[i]).split()))
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
def load_visibility_exclusions() -> frozenset[tuple[str, str]]:
    if not VISIBILITY_EXCLUSIONS_CSV.exists():
        return frozenset()
    with VISIBILITY_EXCLUSIONS_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        return frozenset((row["photo_id"], row["item_name"].strip().lower()) for row in reader)


@dataclass
class ScoredCall:
    record: CallRecord
    predicted_items: list[str]
    ground_truth: list[str]
    matched_predicted: set[int]
    matched_truth: set[int]
    precision: float
    recall_raw: float
    recall_adjusted: float
    f1_raw: float
    f1_adjusted: float


def _f1(precision: float, recall: float) -> float:
    return (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0


def score_call(record: CallRecord) -> ScoredCall:
    ground_truth = load_ground_truth(record.photo_id)
    predicted_items = parse_item_lines(record.text) if record.ok else []

    matched_predicted, matched_truth = assign_matches(predicted_items, ground_truth)

    unmatched_predicted = [item for idx, item in enumerate(predicted_items) if idx not in matched_predicted]
    unmatched_truth = [item for idx, item in enumerate(ground_truth) if idx not in matched_truth]
    for up in unmatched_predicted:
        up_words = set(normalize_phrase(up).split())
        for ut in unmatched_truth:
            ut_words = set(normalize_phrase(ut).split())
            if up_words & ut_words:
                logger.info(
                    "NEAR MISS [%s/%s/%s/rep%d]: predicted %r did not match ground truth %r "
                    "(shared word(s): %s) — review whether the matcher or the model was wrong",
                    record.model, record.prompt_label, record.photo_id, record.rep,
                    up, ut, ", ".join(sorted(up_words & ut_words)),
                )

    exclusions = load_visibility_exclusions()
    adjusted_truth_indices = {
        i for i, item in enumerate(ground_truth) if (record.photo_id, item.strip().lower()) not in exclusions
    }

    precision = len(matched_predicted) / len(predicted_items) if predicted_items else 0.0
    recall_raw = len(matched_truth) / len(ground_truth) if ground_truth else 0.0
    recall_adjusted = (
        len(matched_truth & adjusted_truth_indices) / len(adjusted_truth_indices) if adjusted_truth_indices else 0.0
    )

    return ScoredCall(
        record=record,
        predicted_items=predicted_items,
        ground_truth=ground_truth,
        matched_predicted=matched_predicted,
        matched_truth=matched_truth,
        precision=precision,
        recall_raw=recall_raw,
        recall_adjusted=recall_adjusted,
        f1_raw=_f1(precision, recall_raw),
        f1_adjusted=_f1(precision, recall_adjusted),
    )


def score_all_calls(records: list[CallRecord]) -> list[ScoredCall]:
    reset_synonym_hit_tracking()
    scored = [score_call(r) for r in records]
    for key in {**SYNONYM_MAP, **BRAND_SYNONYMS}:
        if _synonym_hit_counts[key] == 0:
            logger.warning("Synonym/brand entry %r never fired on this benchmark's data — dead entry?", key)
    return scored


def mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    return statistics.mean(values), statistics.stdev(values)


# --------------------------------------------------------------------------
# Legacy matcher — kept ONLY to compute the "before" numbers in the Scoring
# Corrections section of the report. Do not use this for anything else; it
# has the exact bugs described in the task that motivated this rewrite
# (independent per-item lookups instead of bipartite assignment, no
# container-word stripping, and a much smaller synonym map).
# --------------------------------------------------------------------------

_LEGACY_SYNONYM_MAP = {
    "half and half": "heavy cream",
    "half half": "heavy cream",
    "chavroux": "goat cheese",
    "granulated sugar": "sugar",
}
_LEGACY_DISTINCT_PAIRS = frozenset({frozenset({"sweet potato", "potato"})})
_LEGACY_COMPATIBLE_MODIFIERS = COMPATIBLE_MODIFIERS | frozenset({"canned"})


def _legacy_normalize(phrase: str) -> str:
    text = phrase.lower().replace("-", " ")
    text = PUNCTUATION_RE.sub("", text)
    return " ".join(singularize(w) for w in text.split() if w)


def _legacy_match(a_raw: str, b_raw: str) -> bool:
    a_norm = _legacy_normalize(a_raw)
    b_norm = _legacy_normalize(b_raw)
    if frozenset({a_norm, b_norm}) in _LEGACY_DISTINCT_PAIRS:
        return False
    a_canon = _LEGACY_SYNONYM_MAP.get(a_norm, a_norm)
    b_canon = _LEGACY_SYNONYM_MAP.get(b_norm, b_norm)
    if frozenset({a_canon, b_canon}) in _LEGACY_DISTINCT_PAIRS:
        return False
    if a_canon == b_canon:
        return True
    a_words = tuple(a_canon.split())
    b_words = tuple(b_canon.split())
    if not a_words or not b_words:
        return False
    shorter, longer = (a_words, b_words) if len(a_words) <= len(b_words) else (b_words, a_words)
    if longer[-len(shorter):] == shorter:
        extra = longer[: -len(shorter)] if len(shorter) else longer
        if extra and all(w in _LEGACY_COMPATIBLE_MODIFIERS for w in extra):
            return True
    return False


def _legacy_score(record: CallRecord) -> tuple[float, float, float]:
    """Reproduces the pre-fix scoring exactly: independent per-item lookups,
    no consumption tracking, no container stripping."""
    ground_truth = load_ground_truth(record.photo_id)
    predicted = parse_item_lines(record.text) if record.ok else []
    matched_predicted: set[int] = set()
    matched_truth: set[int] = set()
    for pi, p in enumerate(predicted):
        for ti, t in enumerate(ground_truth):
            if _legacy_match(p, t):
                matched_predicted.add(pi)
                matched_truth.add(ti)
    precision = len(matched_predicted) / len(predicted) if predicted else 0.0
    recall = len(matched_truth) / len(ground_truth) if ground_truth else 0.0
    return precision, recall, _f1(precision, recall)


# --------------------------------------------------------------------------
# Running the benchmark (only calls the API for combinations missing from
# the checkpoint — if everything's already there, this makes zero calls)
# --------------------------------------------------------------------------


def run_benchmark(api_key: str) -> list[CallRecord]:
    existing = load_checkpoint()
    logger.info("Loaded %d completed calls from checkpoint at %s", len(existing), CHECKPOINT_PATH)

    plan = list(itertools.product(PHOTO_IDS, MODELS, PROMPTS, range(1, REPETITIONS + 1)))
    total = len(plan)
    missing = [
        (photo_id, model, prompt_label, rep)
        for photo_id, model, (prompt_label, _), rep in plan
        if (model, prompt_label, photo_id, rep) not in existing
    ]

    if not missing:
        logger.info("All %d combinations already checkpointed — re-scoring only, no API calls needed.", total)
        return list(existing.values())

    data_urls: dict[str, str] = {}
    for photo_id in PHOTO_IDS:
        path = IMAGES_DIR / f"{photo_id}.jpg"
        data_urls[photo_id] = build_data_url(path.read_bytes(), "image/jpeg")

    prompt_lookup = dict(PROMPTS)
    limiter = RateLimiterPool()
    done = len(existing)
    for photo_id, model, prompt_label, rep in missing:
        done += 1
        logger.info(
            "[%d/%d] model=%s prompt=%s photo=%s rep=%d", done, total, model, prompt_label, photo_id, rep
        )
        text, usage, latency, error = call_model(
            model, prompt_lookup[prompt_label], api_key, limiter, data_urls[photo_id]
        )
        record = CallRecord(
            model=model, prompt_label=prompt_label, photo_id=photo_id, rep=rep,
            text=text, usage=usage, latency_seconds=latency, error=error,
        )
        if error:
            logger.warning("Call failed: %s", error)
        append_checkpoint(record)
        existing[(model, prompt_label, photo_id, rep)] = record

    return list(existing.values())


# --------------------------------------------------------------------------
# Report rendering
# --------------------------------------------------------------------------


def render_report(scored: list[ScoredCall]) -> str:
    lines: list[str] = []
    lines.append("# Vision Benchmark Report")
    lines.append("")
    lines.append(
        f"{len(MODELS)} models × {len(PROMPTS)} prompts × {len(PHOTO_IDS)} images × {REPETITIONS} reps "
        f"= {len(MODELS) * len(PROMPTS) * len(PHOTO_IDS) * REPETITIONS} calls, all at temperature=0. "
        "Generated by `scripts/benchmark_vision.py`."
    )
    lines.append("")

    total_tokens = sum(
        s.record.usage.get("total_tokens", s.record.usage.get("prompt_tokens", 0) + s.record.usage.get("completion_tokens", 0))
        for s in scored
        if s.record.ok
    )
    failed_calls = sum(1 for s in scored if not s.record.ok)
    lines.append(f"**Total token spend:** {total_tokens:,} tokens across {len(scored)} calls ({failed_calls} failed).")
    lines.append("")
    lines.append(
        "Recall is reported two ways throughout: **raw recall** (against every ground-truth row) and "
        "**visibility-adjusted recall** (excluding items in `test_data/eval_cases/visibility_exclusions.csv` "
        "that are known not to be visible in frame — see that file for reasons)."
    )
    lines.append("")

    # Scoring corrections section
    best_model, best_prompt_label = _find_best_pair(scored)
    legacy_f1s = [
        _legacy_score(s.record)[2]
        for s in scored
        if s.record.model == best_model and s.record.prompt_label == best_prompt_label
    ]
    new_f1s = [
        s.f1_raw for s in scored if s.record.model == best_model and s.record.prompt_label == best_prompt_label
    ]
    legacy_mean, legacy_std = mean_std(legacy_f1s)
    new_mean, new_std = mean_std(new_f1s)

    lines.append("## Scoring corrections")
    lines.append("")
    lines.append(
        "The matcher used in the previous version of this report had three confirmed bugs: it didn't strip "
        "packaging words (\"milk carton\" failed to match \"milk\"), its synonym map only fired on an exact "
        "whole-phrase match (so \"Butter (Chavroux brand)\" never credited goat cheese even though the brand "
        "name is unambiguous), and it scored matches independently per item instead of as a one-to-one "
        "assignment (risking double counting when ground truth has both a general and a specific term, e.g. "
        "\"potato\" and \"sweet potato\"). All three are fixed here: container-word stripping, a two-tier "
        "synonym system (exact-phrase equivalences plus substring-safe brand names), and greedy "
        "most-specific-first bipartite assignment."
    )
    lines.append("")
    lines.append(f"For the best configuration (`{best_model}` + `{best_prompt_label}`), recomputed on the exact same "
                  "checkpointed raw outputs — no new API calls:")
    lines.append("")
    lines.append("| | mean F1 | stddev |")
    lines.append("|---|---|---|")
    lines.append(f"| Before (legacy matcher) | {legacy_mean:.2f} | {legacy_std:.2f} |")
    lines.append(f"| After (corrected matcher) | {new_mean:.2f} | {new_std:.2f} |")
    lines.append("")

    # Per (model, prompt, photo) cells with mean/std and stddev flags
    lines.append("## Per-cell results (mean ± stddev across 3 reps)")
    lines.append("")
    lines.append("| model | prompt | photo | precision | recall (raw) | recall (adj.) | F1 (raw) | F1 (adj.) | flag |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    cells: dict[tuple[str, str, str], list[ScoredCall]] = {}
    for s in scored:
        cells.setdefault((s.record.model, s.record.prompt_label, s.record.photo_id), []).append(s)
    for (model, prompt_label, photo_id), group in sorted(cells.items()):
        p_mean, p_std = mean_std([g.precision for g in group])
        r_mean, r_std = mean_std([g.recall_raw for g in group])
        ra_mean, ra_std = mean_std([g.recall_adjusted for g in group])
        f_mean, f_std = mean_std([g.f1_raw for g in group])
        fa_mean, fa_std = mean_std([g.f1_adjusted for g in group])
        flag = "HIGH VARIANCE" if max(p_std, r_std, f_std) > STDDEV_FLAG_THRESHOLD else ""
        lines.append(
            f"| {model} | {prompt_label} | {photo_id} | {p_mean:.2f}±{p_std:.2f} | "
            f"{r_mean:.2f}±{r_std:.2f} | {ra_mean:.2f}±{ra_std:.2f} | {f_mean:.2f}±{f_std:.2f} | "
            f"{fa_mean:.2f}±{fa_std:.2f} | {flag} |"
        )
    lines.append("")

    # Per-model aggregate
    lines.append("## Per-model aggregate (across all prompts, images, reps)")
    lines.append("")
    lines.append("| model | mean F1 (raw) | stddev | mean F1 (adj.) | stddev |")
    lines.append("|---|---|---|---|---|")
    for model in MODELS:
        f1s = [s.f1_raw for s in scored if s.record.model == model]
        f1as = [s.f1_adjusted for s in scored if s.record.model == model]
        mean, std = mean_std(f1s)
        mean_a, std_a = mean_std(f1as)
        lines.append(f"| {model} | {mean:.2f} | {std:.2f} | {mean_a:.2f} | {std_a:.2f} |")
    lines.append("")

    # Per-prompt aggregate
    lines.append("## Per-prompt aggregate (across all models, images, reps)")
    lines.append("")
    lines.append("| prompt | mean F1 (raw) | stddev | mean F1 (adj.) | stddev |")
    lines.append("|---|---|---|---|---|")
    for prompt_label, _ in PROMPTS:
        f1s = [s.f1_raw for s in scored if s.record.prompt_label == prompt_label]
        f1as = [s.f1_adjusted for s in scored if s.record.prompt_label == prompt_label]
        mean, std = mean_std(f1s)
        mean_a, std_a = mean_std(f1as)
        lines.append(f"| {prompt_label} | {mean:.2f} | {std:.2f} | {mean_a:.2f} | {std_a:.2f} |")
    lines.append("")

    # Ranked (model, prompt) pairs
    lines.append("## Ranked (model, prompt) pairs")
    lines.append("")
    lines.append("| rank | model | prompt | mean F1 (raw) | stddev | mean F1 (adj.) | stddev |")
    lines.append("|---|---|---|---|---|---|---|")
    pair_scores: list[tuple[str, str, float, float, float, float]] = []
    for model in MODELS:
        for prompt_label, _ in PROMPTS:
            f1s = [s.f1_raw for s in scored if s.record.model == model and s.record.prompt_label == prompt_label]
            f1as = [s.f1_adjusted for s in scored if s.record.model == model and s.record.prompt_label == prompt_label]
            mean, std = mean_std(f1s)
            mean_a, std_a = mean_std(f1as)
            pair_scores.append((model, prompt_label, mean, std, mean_a, std_a))
    pair_scores.sort(key=lambda x: x[2], reverse=True)
    for rank, (model, prompt_label, mean, std, mean_a, std_a) in enumerate(pair_scores, start=1):
        lines.append(f"| {rank} | {model} | {prompt_label} | {mean:.2f} | {std:.2f} | {mean_a:.2f} | {std_a:.2f} |")
    lines.append("")
    lines.append(f"**Best configuration: `{best_model}` + `{best_prompt_label}` (mean F1 {new_mean:.2f}).**")
    lines.append("")

    # Per-image breakdown
    lines.append("## Per-image breakdown")
    lines.append("")
    lines.append("| photo | mean F1 (raw) | mean F1 (adj.) | best F1 achieved | flag |")
    lines.append("|---|---|---|---|---|")
    for photo_id in PHOTO_IDS:
        f1s = [s.f1_raw for s in scored if s.record.photo_id == photo_id]
        f1as = [s.f1_adjusted for s in scored if s.record.photo_id == photo_id]
        mean, _ = mean_std(f1s)
        mean_a, _ = mean_std(f1as)
        best = max(f1s) if f1s else 0.0
        flag = "POSSIBLE BAD GROUND TRUTH" if best < BAD_GROUND_TRUTH_F1_THRESHOLD else ""
        lines.append(f"| {photo_id} | {mean:.2f} | {mean_a:.2f} | {best:.2f} | {flag} |")
    lines.append("")

    # Systematic misses
    lines.append("## Systematic misses")
    lines.append("")
    never_identified: dict[str, set[str]] = {}
    for photo_id in PHOTO_IDS:
        gt = load_ground_truth(photo_id)
        matched_anywhere: set[str] = set()
        for s in scored:
            if s.record.photo_id != photo_id:
                continue
            for ti in s.matched_truth:
                matched_anywhere.add(gt[ti])
        never_identified[photo_id] = {item for item in gt if item not in matched_anywhere}

    lines.append("**Ground-truth items no model ever identified, across any run:**")
    lines.append("")
    any_never = False
    for photo_id, items in never_identified.items():
        if items:
            any_never = True
            lines.append(f"- {photo_id}: {', '.join(sorted(items))}")
    if not any_never:
        lines.append("- (none — every ground-truth item was identified by at least one model at least once)")
    lines.append("")

    hallucinated_by_model: dict[str, set[str]] = {model: set() for model in MODELS}
    ever_matched_canonical: set[str] = set()
    example_text_for_canon: dict[str, str] = {}
    for s in scored:
        for idx, item in enumerate(s.predicted_items):
            canon = normalize_phrase(item)
            example_text_for_canon.setdefault(canon, item)
            if idx in s.matched_predicted:
                ever_matched_canonical.add(canon)
            else:
                hallucinated_by_model[s.record.model].add(canon)

    hallucinated_by_all_models = (
        set.intersection(*hallucinated_by_model.values()) if all(hallucinated_by_model.values()) else set()
    )
    hallucinated_by_all_models -= ever_matched_canonical

    lines.append(
        "**Items every model reported that are never in ground truth (hallucinated by all 3 models, in at "
        "least one run each):**"
    )
    lines.append("")
    if hallucinated_by_all_models:
        for canon in sorted(hallucinated_by_all_models):
            lines.append(f"- {example_text_for_canon.get(canon, canon)}")
    else:
        lines.append("- (none found in common across all 3 models)")
    lines.append("")

    # Raw outputs for best configuration only
    lines.append("## Raw outputs — best configuration only")
    lines.append("")
    lines.append(f"`{best_model}` + `{best_prompt_label}`, rep 1 shown per image:")
    lines.append("")
    for photo_id in PHOTO_IDS:
        matches = [
            s for s in scored
            if s.record.model == best_model and s.record.prompt_label == best_prompt_label
            and s.record.photo_id == photo_id and s.record.rep == 1
        ]
        if not matches:
            continue
        s = matches[0]
        lines.append(
            f"**{photo_id}** (precision {s.precision:.2f}, recall raw/adj. {s.recall_raw:.2f}/"
            f"{s.recall_adjusted:.2f}, F1 raw/adj. {s.f1_raw:.2f}/{s.f1_adjusted:.2f}):"
        )
        lines.append("```")
        lines.append(s.record.text if s.record.ok else f"ERROR: {s.record.error}")
        lines.append("```")
    lines.append("")

    return "\n".join(lines)


def _find_best_pair(scored: list[ScoredCall]) -> tuple[str, str]:
    best: tuple[str, str, float] | None = None
    for model in MODELS:
        for prompt_label, _ in PROMPTS:
            f1s = [s.f1_raw for s in scored if s.record.model == model and s.record.prompt_label == prompt_label]
            mean, _ = mean_std(f1s)
            if best is None or mean > best[2]:
                best = (model, prompt_label, mean)
    assert best is not None
    return best[0], best[1]


def main() -> int:
    env = load_env(ENV_PATH)
    api_key = env.get("MISTRAL_API_KEY")
    if not api_key:
        logger.error("MISTRAL_API_KEY not set in .env — cannot run the vision benchmark")
        return 1

    records = run_benchmark(api_key)
    scored = score_all_calls(records)

    report = render_report(scored)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)
    logger.info("Report written to %s", REPORT_PATH)

    failed = sum(1 for s in scored if not s.record.ok)
    if failed:
        logger.warning("%d/%d calls failed — see report and checkpoint for details", failed, len(scored))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
