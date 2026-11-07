"""Orchestrates the eval dimensions: run independently or together, by
name; limit case count for a cheap routine check; write one JSON
Scorecard per run to eval/results/, and print a readable summary.
Every scorecard records model IDs, prompt version hashes, git commit,
and an ISO timestamp, so two runs can be compared later without
guessing what configuration produced either one.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.dimension1 import run_dimension1
from eval.dimension2 import run_dimension2
from eval.dimension3 import run_dimension3
from eval.dimension4 import run_dimension4
from eval.models import DimensionResult, Scorecard
from eval.provenance import component_versions, data_versions, prompt_versions
from mealsight.config.settings import settings
from mealsight.db import close_all, get_pantry_db

RESULTS_DIR = Path(__file__).resolve().parent / "results"

DIMENSIONS = ("dimension1", "dimension2", "dimension3", "dimension4", "dimension5")


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=5
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


DEMO_PANTRY_FIXTURE = Path(__file__).resolve().parents[2] / "test_data" / "demo_pantry.json"


def describe_pantry_fixture(path: Path = DEMO_PANTRY_FIXTURE) -> dict[str, Any]:
    """What scripts/reset_demo_pantry.py seeds, in the words the scorecard
    reports: which real photos supplied the perishables, which staples were
    added by hand, and a hash of the file so a changed seed is visible."""
    raw = path.read_bytes()
    fixture = json.loads(raw)
    return {
        "fixture": path.name,
        "fixture_sha256": hashlib.sha256(raw).hexdigest()[:12],
        "photo_sources": {photo: len(items) for photo, items in fixture["photos"].items()},
        "photo_items_note": "raw analyze_fridge_photo output, uncurated; "
        "duplicates across photos collapse to one row",
        "staples_added_by_hand": [item["name"] for item in fixture["staples"]],
        "staples_note": "oil, salt, pepper, flour, sugar and common dried spices; no eggs, rice, pasta or "
        "proteins were added",
    }


async def pantry_snapshot() -> dict[str, Any]:
    """The pantry the run started from. A missing pantry database or table is RECORDED, not raised: the
    deterministic matcher dimension carries its own pantry state and must not need this one, and a run on
    a machine with no pantry should say so in the scorecard. The hash is None then (never a hash of
    nothing), and the regression gate treats an absent pantry as a mismatch against the baseline."""
    try:
        rows = await get_pantry_db().fetch_all(
            "SELECT name, quantity, estimated_shelf_days FROM pantry ORDER BY name"
        )
    except sqlite3.OperationalError as exc:  # aiosqlite re-raises sqlite3's own error
        return {
            **describe_pantry_fixture(),
            "pantry_present": False,
            "rows_at_run_start": None,
            "pantry_content_sha256": None,
            "pantry_absent_reason": f"{type(exc).__name__}: {exc}",
        }
    digest = hashlib.sha256(
        json.dumps([[r["name"], r["quantity"], r["estimated_shelf_days"]] for r in rows]).encode()
    ).hexdigest()[:12]
    return {
        **describe_pantry_fixture(),
        "pantry_present": True,
        "rows_at_run_start": len(rows),
        "pantry_content_sha256": digest,
    }


SCORER_NOTES = [
    "Dimension 1 baseline SUPERSEDES the earlier F1 0.64 (mistral-medium-2505) and 0.55 (ministral-8b-2512) "
    "figures. Two scorer corrections make those numbers non-comparable, and both can only lower a score: "
    "(1) a photo where the model identified nothing now counts as a zero instead of being dropped from the "
    "mean; (2) 'green onion' no longer matches ground-truth 'onion' (a scallion is not a bulb onion). A "
    "lower number than 0.55 is therefore not by itself a model regression.",
    "Dimension 2 now enforces hand-authored constraints (eval/cases.py) in addition to what the pipeline "
    "extracted, whole-word avoid matching, and a dimension verdict that requires every case to pass.",
    "Dimension 2 corrections after run_1793926853: expectations for d2_10, d2_12 and d2_30 were corrected "
    "(see eval/cases.py CORRECTIONS); only a user-STATED cook-time limit is enforced by the scorer, not the "
    "profile default. The pipeline changed too: stated-vs-default cook time, relaxation on "
    "'nothing cookable', code-level avoid-list exclusion, and a deterministic dietary-restriction "
    "backstop. Compare this run to run_1793926853 with those changes in mind; they are not like-for-like.",
    "Dimension 3 (match accuracy) checks the matcher's arithmetic against hand-derived values, 32 cases; "
    "Dimensions 4 and 5 run each case against a throwaway pantry/profile database (eval/isolation.py), reset "
    "and verified empty between cases, and fingerprint the real pantry, user and recipe databases before and "
    "after (they must be unchanged). The pass thresholds for 4 and 5 (0.80) were fixed before their first "
    "run. Dimension 5 also reports cases that passed on outcome while the system's own scoring did not "
    "reflect the profile (passed_without_scoring_support): those passes came from tie-breaking or the "
    "language model.",
]


def _git_state() -> tuple[bool, str]:
    """Whether uncommitted changes exist, and a hash of them, so a scorecard
    can say exactly which code it measured."""
    try:
        diff = subprocess.run(["git", "diff", "HEAD"], capture_output=True, check=True, timeout=20).stdout
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        ).stdout
        digest = hashlib.sha256(diff + untracked.encode()).hexdigest()[:12]
        return bool(diff or untracked.strip()), digest
    except Exception:
        return False, "unknown"


def _print_summary(scorecard: Scorecard) -> None:
    print(f"\n=== MealSight eval run {scorecard.run_id} ===")
    print(
        f"commit={scorecard.git_commit}  dirty={scorecard.git_dirty} ({scorecard.git_diff_sha256})  "
        f"timestamp={scorecard.timestamp}"
    )
    pantry = scorecard.pantry
    print(
        f"pantry: {pantry.get('rows_at_run_start')} rows, fixture {pantry.get('fixture')} "
        f"({pantry.get('fixture_sha256')}), content {pantry.get('pantry_content_sha256')}"
    )
    for dim in scorecard.dimensions:
        status = "PASS" if dim.passed else "FAIL"
        print(
            f"\n[{status}] {dim.name}  score={dim.score:.3f} "
            f"(threshold={dim.pass_threshold:.3f})  cases={dim.case_count}  "
            f"api_calls={dim.api_calls}  tokens={dim.total_tokens}  "
            f"wall_clock={dim.wall_clock_seconds:.1f}s"
        )
        for key, value in dim.metrics.items():
            print(f"    {key}: {value}")
        for violation in [v for r in dim.case_results for v in r.violations]:
            print(f"    VIOLATION [{violation.case_id}] {violation.constraint}: {violation.detail}")
    for note in scorecard.notes:
        print(f"note: {note}")
    overall = "PASS" if scorecard.passed else "FAIL"
    print(f"\n=== overall: {overall} ===\n")


async def run_eval(
    dimensions: tuple[str, ...] = DIMENSIONS,
    case_limit: int | None = None,
    sampled: bool = False,
) -> Scorecard:
    results: list[DimensionResult] = []
    pantry = await pantry_snapshot()

    if "dimension1" in dimensions:
        results.append(await run_dimension1(case_limit=case_limit))
    if "dimension2" in dimensions:
        results.append(await run_dimension2(case_limit=case_limit, sampled=sampled))
    if "dimension3" in dimensions:
        results.append(await run_dimension3(case_limit=case_limit))
    if "dimension4" in dimensions:
        results.append(await run_dimension4(case_limit=case_limit))
    if "dimension5" in dimensions:
        from eval.dimension5 import run_dimension5

        results.append(await run_dimension5(case_limit=case_limit))

    run_id = f"run_{int(time.time())}"
    git_dirty, git_diff_sha256 = _git_state()
    scorecard = Scorecard(
        run_id=run_id,
        timestamp=datetime.now(UTC).isoformat(),
        git_commit=_git_commit(),
        model_ids={
            "vision_model": settings.VISION_MODEL,
            "reasoning_model": settings.REASONING_MODEL,
            "extraction_model": settings.EXTRACTION_MODEL,
        },
        prompt_versions=prompt_versions(),
        component_versions=component_versions(),
        data_versions=await data_versions(),
        dimensions=results,
        passed=all(d.passed for d in results),
        pantry=pantry,
        notes=SCORER_NOTES,
        git_dirty=git_dirty,
        git_diff_sha256=git_diff_sha256,
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{run_id}.json"
    out_path.write_text(scorecard.model_dump_json(indent=2))

    _print_summary(scorecard)
    print(f"scorecard written to {out_path}")

    # Close every shared database handle. An open aiosqlite connection keeps a non-daemon thread alive, so
    # without this the process never exited after writing the scorecard, which would hang a CI job.
    await close_all()
    return scorecard
