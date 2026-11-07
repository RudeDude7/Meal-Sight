#!/usr/bin/env python3
"""Measures constraint-extraction accuracy against both real corpora
(test_data/text/text_inputs.json: 10 typed inputs; test_data/text/
voice_scripts.json + test_data/audio/memo_NN.mp3: 20 voice memos) with real
API calls, and reports per-field accuracy plus any polarity inversion.

Scored fields, as established in phases 5.2/5.3 and reported in phase 9.2:
servings, max_cook_time_minutes, dietary_restrictions, avoid_dishes,
cuisine_preference, protein_preference, avoid_ingredients (7 fields per
input: 70 for text, 140 for voice). List fields compare as sets of
lowercased strings, strictly (so "mushroom" vs "mushrooms" is a miss, as
it was in the published 98.6% / 97.9% figures); a singular/plural-tolerant
number is printed alongside.

POLARITY: an extraction that puts something the speaker WANTS into an
avoid_* field, or something they want to AVOID into protein/cuisine, is
worse than a missed field, so it is checked separately. Every field-level
disagreement is also printed, so the polarity check never has to be taken
on trust.

The two corpora above contain no request that WANTS an ingredient ("with
chicken"), so they cannot detect a flipped polarity; the "polarity" mode runs
test_data/text/polarity_probes.json (want/avoid phrasings, each repeated
POLARITY_REPS times because extraction is not deterministic even at
temperature 0) and counts wrong outcomes. A probe is wrong when a WANTED item
lands in an avoid field, or an AVOIDED item fails to land in one (or lands in
protein_preference).

Run from the backend directory (real API calls, bills tokens):
    PYTHONPATH=. .venv/bin/python ../scripts/measure_extraction_accuracy.py [text|voice|both|polarity|possession]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TEXT_CORPUS = REPO_ROOT / "test_data" / "text" / "text_inputs.json"
VOICE_CORPUS = REPO_ROOT / "test_data" / "text" / "voice_scripts.json"
AUDIO_DIR = REPO_ROOT / "test_data" / "audio"
POLARITY_PROBES = REPO_ROOT / "test_data" / "text" / "polarity_probes.json"
POLARITY_REPS = 3
POSSESSION_PROBES = REPO_ROOT / "test_data" / "text" / "possession_probes.json"

SCALAR_FIELDS = ["servings", "max_cook_time_minutes", "cuisine_preference", "protein_preference"]
LIST_FIELDS = ["dietary_restrictions", "avoid_dishes", "avoid_ingredients"]
FIELDS = ["servings", "max_cook_time_minutes", "dietary_restrictions", "avoid_dishes",
          "cuisine_preference", "protein_preference", "avoid_ingredients"]


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _as_set(values: list[str], lenient: bool) -> set[str]:
    items = {_norm(v) for v in values}
    return {" ".join(_stem(w) for w in i.split()) for i in items} if lenient else items


def field_matches(field: str, expected: Any, actual: Any, lenient: bool) -> bool:
    if field in LIST_FIELDS:
        return _as_set(expected or [], lenient) == _as_set(actual or [], lenient)
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, int | float):
        return expected == actual
    left, right = _norm(expected), _norm(actual)
    if lenient:
        left, right = _stem(left), _stem(right)
    return left == right


def polarity_flags(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Two directions of inversion, in terms of the 'thing' named, not
    the field's whole value."""
    flags: list[str] = []
    exp_avoid = _as_set((expected.get("avoid_ingredients") or []) + (expected.get("avoid_dishes") or []), True)
    exp_want = {
        _stem(_norm(v)) for v in (expected.get("protein_preference"), expected.get("cuisine_preference")) if v
    }
    act_avoid = _as_set((actual.get("avoid_ingredients") or []) + (actual.get("avoid_dishes") or []), True)
    act_want = {
        _stem(_norm(v)) for v in (actual.get("protein_preference"), actual.get("cuisine_preference")) if v
    }
    for item in sorted(act_avoid & exp_want):
        flags.append(f"WANTED '{item}' extracted as AVOID")
    for item in sorted(act_want & exp_avoid):
        flags.append(f"AVOIDED '{item}' extracted as WANTED (protein/cuisine)")
    return flags


async def _run_polarity() -> None:
    from mealsight.perception.processor import analyze_text_input

    wrong = 0
    total = 0
    for probe in json.loads(POLARITY_PROBES.read_text()):
        item = _stem(_norm(probe["item"]))
        for _ in range(POLARITY_REPS):
            result = (await analyze_text_input(probe["text"])).model_dump()
            avoid = " ".join(_stem(_norm(v)) for v in result["avoid_ingredients"] + result["avoid_dishes"])
            protein = _stem(_norm(result.get("protein_preference") or ""))
            context = _norm(result.get("additional_context") or "")
            if probe["polarity"] == "want":
                problem = "WANTED item landed in an avoid field" if item in avoid else None
                captured = item in protein or item in _stem(context)
            else:
                problem = (
                    "AVOIDED item missing from avoid fields" if item not in avoid
                    else "AVOIDED item also set as protein_preference" if item in protein else None
                )
                captured = True
            total += 1
            if problem or not captured:
                wrong += 1
                print(f"  WRONG [{probe['id']}] {probe['text']!r}: {problem or 'wanted item not captured anywhere'}"
                      f" (avoid={result['avoid_ingredients']}, protein={result['protein_preference']!r}, ctx={result['additional_context']!r})", flush=True)
    print(f"\n=== POLARITY PROBES: {wrong} wrong of {total} ({wrong / total:.1%}) ===")
    sys.stdout.flush()
    os._exit(0)


async def _run_possession() -> None:
    """Can extraction tell "I HAVE X" from "I WANT X"? Each probe lists the
    foods that must appear in ingredients_on_hand and the foods that must
    not (wanted, negated, or gone). Repeated POLARITY_REPS times."""
    from mealsight.perception.processor import analyze_text_input

    wrong = 0
    total = 0
    for probe in json.loads(POSSESSION_PROBES.read_text()):
        for _ in range(POLARITY_REPS):
            result = (await analyze_text_input(probe["text"])).model_dump()
            on_hand = [set(_stem(w) for w in _norm(v).split()) for v in result["ingredients_on_hand"]]
            missing = [h for h in probe["have"] if not any(set(_stem(w) for w in h.split()) <= got for got in on_hand)]
            leaked = [n for n in probe["not_have"] if any(_stem(n) in got for got in on_hand)]
            total += 1
            if missing or leaked:
                wrong += 1
                print(f"  WRONG [{probe['id']}] {probe['text']!r}: missing={missing} leaked={leaked} "
                      f"(on_hand={result['ingredients_on_hand']}, protein={result['protein_preference']!r})", flush=True)
    print(f"\n=== POSSESSION PROBES: {wrong} wrong of {total} ({wrong / total:.1%}) ===")
    sys.stdout.flush()
    os._exit(0)


async def _run(which: str) -> int:
    if which == "possession":
        await _run_possession()
    if which == "polarity":
        await _run_polarity()
    from mealsight.perception.processor import analyze_text_input, analyze_voice_memo

    cases: list[tuple[str, str, dict[str, Any], Any]] = []
    if which in ("text", "both"):
        for row in json.loads(TEXT_CORPUS.read_text()):
            cases.append(("text", row["id"], row, None))
    if which in ("voice", "both"):
        for row in json.loads(VOICE_CORPUS.read_text()):
            cases.append(("voice", row["id"], row, None))

    totals: dict[str, dict[str, list[int]]] = {"text": {f: [0, 0, 0] for f in FIELDS}, "voice": {f: [0, 0, 0] for f in FIELDS}}
    inversions: list[str] = []
    diffs: list[str] = []
    for kind, case_id, row, _ in cases:
        if kind == "text":
            perception = await analyze_text_input(row["text"])
            utterance = row["text"]
        else:
            perception = await analyze_voice_memo((AUDIO_DIR / f"{case_id}.mp3").read_bytes())
            utterance = getattr(perception, "raw_transcript", "") or row["script"]
        actual = perception.model_dump()
        expected = row["expected_constraints"]
        for field in FIELDS:
            strict = field_matches(field, expected.get(field), actual.get(field), lenient=False)
            lenient = field_matches(field, expected.get(field), actual.get(field), lenient=True)
            totals[kind][field][0] += int(strict)
            totals[kind][field][1] += int(lenient)
            totals[kind][field][2] += 1
            if not strict:
                diffs.append(f"[{kind} {case_id}] {field}: expected {expected.get(field)!r} got {actual.get(field)!r}   <- {utterance!r}")
        for flag in polarity_flags(expected, actual):
            inversions.append(f"[{kind} {case_id}] {flag}   <- {utterance!r}")
        print(f"done {kind} {case_id}", flush=True)

    for kind in ("text", "voice"):
        rows = totals[kind]
        n_cases = sum(1 for c in cases if c[0] == kind)
        if n_cases == 0:
            continue
        print(f"\n=== {kind.upper()} ({n_cases} inputs, {n_cases * len(FIELDS)} scored fields) ===")
        strict_total = lenient_total = 0
        for field in FIELDS:
            s, le, n = rows[field]
            strict_total += s
            lenient_total += le
            print(f"  {field:24s} strict {s}/{n} ({s / n:.1%})   plural-tolerant {le}/{n} ({le / n:.1%})")
        grand = n_cases * len(FIELDS)
        print(f"  {'OVERALL':24s} strict {strict_total}/{grand} ({strict_total / grand:.1%})   plural-tolerant {lenient_total}/{grand} ({lenient_total / grand:.1%})")
    print(f"\n=== POLARITY INVERSIONS: {len(inversions)} ===")
    for line in inversions:
        print("  " + line)
    print(f"\n=== EVERY STRICT FIELD DISAGREEMENT ({len(diffs)}) ===")
    for line in diffs:
        print("  " + line)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(_run(sys.argv[1] if len(sys.argv) > 1 else "both"))
