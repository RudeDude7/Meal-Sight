#!/usr/bin/env python3
"""Sanity-check the MealSight test-data corpus before it's relied on for eval.

Checks images, audio, CSV ground truth, and the two JSON script files all
line up with each other and with what's actually on disk, then prints a
summary table. Exits non-zero if anything is missing or malformed.

Run with: uv run --with Pillow scripts/validate_test_data.py
"""

from __future__ import annotations

import csv
import json
import logging
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "test_data" / "images"
AUDIO_DIR = REPO_ROOT / "test_data" / "audio"
EVAL_CASES_DIR = REPO_ROOT / "test_data" / "eval_cases"
TEXT_DIR = REPO_ROOT / "test_data" / "text"

CSV_PATH = EVAL_CASES_DIR / "image_ground_truth.csv"
VOICE_SCRIPTS_PATH = TEXT_DIR / "voice_scripts.json"
TEXT_INPUTS_PATH = TEXT_DIR / "text_inputs.json"

EXPECTED_IMAGE_COUNT = 30
EXPECTED_AUDIO_COUNT = 20
MIN_IMAGE_DIMENSION = 100
FFPROBE_TIMEOUT_SECONDS = 10

CATEGORIES = {
    "protein", "vegetable", "fruit", "grain", "dairy",
    "condiment", "spice", "beverage", "other",
}
CSV_COLUMNS = {"photo_id", "item_name", "source_class", "category"}
EXPECTED_CONSTRAINT_KEYS = {
    "servings",
    "max_cook_time_minutes",
    "dietary_restrictions",
    "avoid_ingredients",
    "avoid_dishes",
    "cuisine_preference",
    "protein_preference",
    "mood_or_preference",
}


class Status(Enum):
    OK = "OK"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str


def check_images() -> CheckResult:
    name = "Images (30 present, openable, sane size)"
    expected_files = {f"photo_{i:02d}.jpg" for i in range(1, EXPECTED_IMAGE_COUNT + 1)}
    present_files = {p.name for p in IMAGES_DIR.glob("photo_*.jpg")} if IMAGES_DIR.exists() else set()

    missing = expected_files - present_files
    unexpected = present_files - expected_files
    problems: list[str] = []
    if missing:
        problems.append(f"missing: {sorted(missing)}")
    if unexpected:
        problems.append(f"unexpected extra files: {sorted(unexpected)}")

    for filename in sorted(present_files & expected_files):
        path = IMAGES_DIR / filename
        try:
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                width, height = img.size
        except (UnidentifiedImageError, OSError) as exc:
            problems.append(f"{filename}: not openable ({exc})")
            continue
        if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
            problems.append(f"{filename}: suspiciously small ({width}x{height})")

    if problems:
        return CheckResult(name, Status.FAIL, "; ".join(problems))
    return CheckResult(name, Status.OK, f"{len(present_files)} images present and valid")


def check_csv_matches_images() -> CheckResult:
    name = "CSV <-> image files consistency"
    if not CSV_PATH.exists():
        return CheckResult(name, Status.FAIL, f"{CSV_PATH} does not exist")

    with CSV_PATH.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or set(reader.fieldnames) != CSV_COLUMNS:
            return CheckResult(name, Status.FAIL, f"unexpected columns: {reader.fieldnames}")
        rows = list(reader)

    if not rows:
        return CheckResult(name, Status.FAIL, "CSV has no rows")

    csv_photo_ids = {row["photo_id"] for row in rows}
    image_photo_ids = {p.stem for p in IMAGES_DIR.glob("photo_*.jpg")} if IMAGES_DIR.exists() else set()

    missing_files = csv_photo_ids - image_photo_ids
    missing_rows = image_photo_ids - csv_photo_ids
    problems: list[str] = []
    if missing_files:
        problems.append(f"photo_ids in CSV with no matching file: {sorted(missing_files)}")
    if missing_rows:
        problems.append(f"image files with no CSV row: {sorted(missing_rows)}")

    bad_categories = {row["category"] for row in rows} - CATEGORIES
    if bad_categories:
        problems.append(f"unrecognized categories in CSV: {sorted(bad_categories)}")

    if problems:
        return CheckResult(name, Status.FAIL, "; ".join(problems))
    return CheckResult(name, Status.OK, f"{len(rows)} rows across {len(csv_photo_ids)} photos, all matched")


def probe_audio_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
        return float(payload["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def check_audio() -> CheckResult:
    name = "Audio (20 present, non-zero length, playable)"
    expected_files = {f"memo_{i:02d}.mp3" for i in range(1, EXPECTED_AUDIO_COUNT + 1)}
    present_files = {p.name for p in AUDIO_DIR.glob("memo_*.mp3")} if AUDIO_DIR.exists() else set()

    missing = expected_files - present_files
    problems: list[str] = []
    if missing:
        problems.append(f"missing: {sorted(missing)}")

    for filename in sorted(present_files & expected_files):
        path = AUDIO_DIR / filename
        if path.stat().st_size == 0:
            problems.append(f"{filename}: zero bytes")
            continue
        duration = probe_audio_duration(path)
        if duration is None:
            problems.append(f"{filename}: ffprobe couldn't read it")
        elif duration <= 0:
            problems.append(f"{filename}: zero duration")

    if problems:
        return CheckResult(name, Status.FAIL, "; ".join(problems))
    return CheckResult(name, Status.OK, f"{len(present_files)} audio files present and playable")


def load_json_or_none(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def validate_constraint_entries(entries: list[dict[str, Any]], require_id_prefix: str | None) -> list[str]:
    problems: list[str] = []
    for entry in entries:
        entry_id = entry.get("id", "<no id>")
        if "expected_constraints" not in entry:
            problems.append(f"{entry_id}: missing expected_constraints")
            continue
        constraints = entry["expected_constraints"]
        if not isinstance(constraints, dict):
            problems.append(f"{entry_id}: expected_constraints is not an object")
            continue
        missing_keys = EXPECTED_CONSTRAINT_KEYS - set(constraints.keys())
        if missing_keys:
            problems.append(f"{entry_id}: expected_constraints missing keys {sorted(missing_keys)}")
        if require_id_prefix and not str(entry_id).startswith(require_id_prefix):
            problems.append(f"{entry_id}: id doesn't start with '{require_id_prefix}'")
    return problems


def check_voice_scripts_and_audio() -> CheckResult:
    name = "voice_scripts.json <-> audio consistency + schema"
    entries = load_json_or_none(VOICE_SCRIPTS_PATH)
    if entries is None:
        return CheckResult(name, Status.FAIL, f"{VOICE_SCRIPTS_PATH} missing or not valid JSON")
    if not isinstance(entries, list):
        return CheckResult(name, Status.FAIL, "voice_scripts.json is not a JSON array")

    problems = validate_constraint_entries(entries, require_id_prefix="memo_")
    for entry in entries:
        entry_id = entry.get("id")
        if entry_id is None:
            continue
        if not (AUDIO_DIR / f"{entry_id}.mp3").exists():
            problems.append(f"{entry_id}: no matching audio file")
        if not entry.get("script"):
            problems.append(f"{entry_id}: empty script text")
        if not entry.get("voice_used"):
            problems.append(f"{entry_id}: voice_used not recorded")

    if problems:
        return CheckResult(name, Status.FAIL, "; ".join(problems))
    return CheckResult(name, Status.OK, f"{len(entries)} scripts, all matched to audio with valid schema")


def check_text_inputs() -> CheckResult:
    name = "text_inputs.json schema"
    entries = load_json_or_none(TEXT_INPUTS_PATH)
    if entries is None:
        return CheckResult(name, Status.FAIL, f"{TEXT_INPUTS_PATH} missing or not valid JSON")
    if not isinstance(entries, list):
        return CheckResult(name, Status.FAIL, "text_inputs.json is not a JSON array")

    problems = validate_constraint_entries(entries, require_id_prefix="text_")
    for entry in entries:
        entry_id = entry.get("id", "<no id>")
        if not entry.get("text"):
            problems.append(f"{entry_id}: empty text field")

    if problems:
        return CheckResult(name, Status.FAIL, "; ".join(problems))
    return CheckResult(name, Status.OK, f"{len(entries)} entries, schema valid")


def print_summary(results: list[CheckResult]) -> None:
    name_width = max(len(r.name) for r in results) + 2
    print("\n" + "=" * 100)
    print("MEALSIGHT TEST DATA VALIDATION")
    print("=" * 100)
    print(f"{'CHECK':<{name_width}}{'STATUS':<8}DETAIL")
    print("-" * 100)
    for r in results:
        print(f"{r.name:<{name_width}}{r.status.value:<8}{r.detail}")
    print()
    passed = sum(1 for r in results if r.status is Status.OK)
    failed = sum(1 for r in results if r.status is Status.FAIL)
    print(f"PASS: {passed}  FAIL: {failed}")


def main() -> int:
    results = [
        check_images(),
        check_csv_matches_images(),
        check_audio(),
        check_voice_scripts_and_audio(),
        check_text_inputs(),
    ]
    print_summary(results)
    return 1 if any(r.status is Status.FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
