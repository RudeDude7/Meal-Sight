"""The regression gate: compares an evaluation scorecard with the recorded baseline.

WHY NOT "FAIL THE BUILD IF THE SUITE FAILS". The suite legitimately fails: Dimension 1 sits at 0.488
against a 0.60 threshold for a documented external reason (the original vision model was retired and
the replacement tier is the only one reachable on the free plan; docs/EVALUATION.md section 4). A
gate on the overall verdict would be red permanently, and a permanently red pipeline is a pipeline
nobody reads. The property worth enforcing is REGRESSION: a dimension that falls below where it was
last recorded, or a safety invariant that stops holding, fails loudly; a known-failing dimension
that stays at its known level does not.

WHAT FAILS THE GATE (each is reported with the numbers):
  * a baseline dimension is missing from the scorecard (the suite silently lost a dimension);
  * its pass threshold changed (nobody lowers a bar to make a number pass);
  * it ran fewer cases than the baseline (cases silently dropped);
  * its score fell more than the dimension's noise tolerance below the baseline;
  * a safety invariant broke (any hard-constraint violation, any matcher disagreement, a case defect, or
    the
    real databases being touched);
  * the scorecard or the baseline cannot be read (a broken gate must not read as a passing one).
  * an ABORTED scorecard (infrastructure failure, eval/circuit.py) is refused outright, exit 2: it is never
    compared and never accepted as a baseline.

WHAT DOES NOT: a score within the tolerance band (model nondeterminism), a known-failing dimension at its
  known
level, an improvement (reported, with a note to refresh the baseline), extra cases (reported).

TOLERANCES are per dimension and recorded in the baseline with their evidence. They are deliberately
small: one case for the case-count dimensions, and a band just wider than the observed run-to-run
spread for Dimension 1 (0.485 to 0.492 over five runs).

Exit codes: 0 gate passed, 1 regression found, 2 the gate itself could not run.

    python -m eval.compare eval/results/run_X.json                      # compare against the baseline
    python -m eval.compare run_X.json --only dimension3 --strict-data   # the per-PR matcher gate
    python -m eval.compare run_X.json --update --reason "why"           # refresh the baseline (review
  it!)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASELINE_PATH = Path(__file__).resolve().parent / "baseline" / "baseline.json"

OK = "OK"
NOISE = "OK (within noise band)"
KNOWN = "KNOWN FAILING (at baseline)"
IMPROVED = "IMPROVED"
RECOVERED = "RECOVERED"
REGRESSION = "REGRESSION"
WARN = "WARN"

# Reference data whose hashes must match when the matcher gate runs on a deterministic rebuild.
DETERMINISTIC_DATA = ("recipe_corpus", "ingredient_synonyms", "substitutions", "nutrition_reference")


@dataclass
class Finding:
    dimension: str
    status: str
    detail: str
    baseline_score: float | None = None
    score: float | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def is_regression(self) -> bool:
        return self.status == REGRESSION


@dataclass
class Report:
    findings: list[Finding]
    notes: list[str]

    @property
    def passed(self) -> bool:
        return not any(f.is_regression for f in self.findings)


def _short(name: str) -> str:
    return name.split("_", 1)[0]


def _metric(metrics: dict[str, Any], path: str) -> Any:
    value: Any = metrics
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def compare(
    scorecard: dict[str, Any],
    baseline: dict[str, Any],
    *,
    only: set[str] | None = None,
    strict_data: bool = False,
) -> Report:
    by_name = {d["name"]: d for d in scorecard.get("dimensions", [])}
    findings: list[Finding] = []
    notes: list[str] = []

    for name, base in baseline["dimensions"].items():
        if only and _short(name) not in only and name not in only:
            continue
        got = by_name.get(name)
        if got is None:
            findings.append(
                Finding(name, REGRESSION, "the dimension did not run / is missing from the scorecard")
            )
            continue

        problems: list[str] = []
        tolerance = float(base.get("tolerance", 0.0))
        base_score, score = float(base["score"]), float(got["score"])

        if abs(float(got["pass_threshold"]) - float(base["threshold"])) > 1e-9:
            problems.append(
                f"pass threshold changed: baseline {base['threshold']}, scorecard {got['pass_threshold']}"
            )
        if got["case_count"] < base["case_count"]:
            problems.append(f"ran {got['case_count']} cases, baseline has {base['case_count']}")
        for path, expected in (base.get("invariants") or {}).items():
            actual = _metric(got.get("metrics", {}), path)
            if actual != expected:
                problems.append(f"invariant broken: {path} is {actual!r}, must be {expected!r}")
        if score < base_score - tolerance - 1e-9:
            problems.append(
                f"score {score:.4f} is below the baseline {base_score:.4f} by more than the "
                f"tolerance {tolerance:.4f}"
            )

        if problems:
            findings.append(Finding(name, REGRESSION, "; ".join(problems), base_score, score, problems))
            continue

        status, detail = OK, f"score {score:.4f} (baseline {base_score:.4f})"
        if base.get("status") == "known_failing":
            if got.get("passed"):
                status = RECOVERED
                detail += f"; now PASSES its {got['pass_threshold']} threshold: refresh the baseline"
            elif score > base_score + tolerance:
                status = IMPROVED
                detail += "; above the known level: refresh the baseline"
            else:
                status = KNOWN
                why = base.get("reason", "")
                detail += f"; fails threshold {base['threshold']} for a documented reason ({why})"
        elif score > base_score + tolerance + 1e-9:
            status, detail = IMPROVED, detail + "; above the baseline: refresh it"
        elif score < base_score - 1e-9:
            status, detail = NOISE, detail + "; below the baseline but inside the tolerance band"
        if base.get("status") != "known_failing" and not got.get("passed") and status in (OK, NOISE):
            status, detail = WARN, detail + f"; the dimension is below its own threshold {base['threshold']}"
        if got["case_count"] > base["case_count"]:
            notes.append(
                f"{name}: {got['case_count']} cases against a baseline of {base['case_count']}; refresh it"
            )
        findings.append(Finding(name, status, detail, base_score, score))

    # Provenance: what differs between the recorded run and this one.
    for group in ("model_ids", "prompt_versions", "component_versions", "data_versions"):
        was, now = baseline.get("provenance", {}).get(group, {}), scorecard.get(group, {})
        for key in sorted(set(was) | set(now)):
            if was.get(key) != now.get(key):
                line = f"{group}.{key}: baseline {was.get(key)} -> scorecard {now.get(key)}"
                if strict_data and group == "data_versions" and key in DETERMINISTIC_DATA:
                    findings.append(
                        Finding(
                            "provenance",
                            REGRESSION,
                            f"{line} (the rebuilt reference data is not what the baseline was recorded on)",
                        )
                    )
                else:
                    notes.append("provenance differs: " + line)
    # The pantry the run started from. Dimensions 1, 2, 4 and 5 depend on it, so a different or absent
    # pantry makes the comparison meaningless. Dimension 3 carries its own pantry state and does not.
    expected = baseline.get("provenance", {}).get("pantry_content_sha256")
    pantry = scorecard.get("pantry") or {}
    actual = pantry.get("pantry_content_sha256")
    pantry_dims = [n for n in baseline["dimensions"] if _short(n) != "dimension3"]
    ran_pantry_dependent = any(
        n in by_name and (not only or _short(n) in only or n in only) for n in pantry_dims
    )
    if expected and actual != expected:
        line = (
            f"pantry content: baseline {expected} ({baseline['provenance'].get('pantry_rows')} rows) -> "
            f"scorecard {actual} ({pantry.get('rows_at_run_start')} rows"
            + ("" if pantry.get("pantry_present", True) else ", pantry ABSENT")
            + ")"
        )
        if strict_data and ran_pantry_dependent:
            findings.append(Finding("provenance", REGRESSION, line + " (not the pantry the baseline used)"))
        else:
            notes.append("provenance differs: " + line)
    return Report(findings, notes)


def render_markdown(report: Report, scorecard_name: str) -> str:
    lines = [
        f"### Evaluation regression gate: {'PASSED' if report.passed else 'FAILED'}",
        f"Scorecard `{scorecard_name}` against `eval/baseline/baseline.json`.",
        "",
        "| Dimension | Result | Detail |",
        "|---|---|---|",
    ]
    for f in report.findings:
        lines.append(f"| {f.dimension} | **{f.status}** | {f.detail} |")
    if report.notes:
        lines += ["", "Notes:"] + [f"- {n}" for n in report.notes]
    lines += [
        "",
        "A known-failing dimension at its known level does not fail the gate; a regression does. "
        "See docs/EVALUATION.md and docs/CI.md.",
    ]
    return "\n".join(lines)


def build_baseline_update(scorecard: dict[str, Any], baseline: dict[str, Any], reason: str) -> dict[str, Any]:
    """The baseline refreshed from a scorecard. Tolerances, statuses, reasons and invariants are kept:
    refreshing the numbers must not quietly widen a tolerance or relabel a failing dimension."""
    new: dict[str, Any] = json.loads(json.dumps(baseline))
    for d in scorecard["dimensions"]:
        entry = new["dimensions"].get(d["name"])
        if entry is None:
            raise SystemExit(
                f"{d['name']} is not in the baseline; add it by hand with a tolerance and invariants."
            )
        entry["score"] = round(float(d["score"]), 4)
        entry["threshold"] = d["pass_threshold"]
        entry["case_count"] = d["case_count"]
        if entry.get("status") == "known_failing" and d.get("passed"):
            entry["status"] = "passing"
            entry["reason"] = "recovered: now passes its threshold"
    new["recorded_from"] = scorecard.get("run_id")
    new["recorded_at"] = datetime.now(UTC).isoformat()
    new["update_reason"] = reason
    new["provenance"] = {
        g: scorecard.get(g, {})
        for g in ("model_ids", "prompt_versions", "component_versions", "data_versions")
    }
    pantry = scorecard.get("pantry") or {}
    new["provenance"]["pantry_fixture_sha256"] = pantry.get("fixture_sha256")
    new["provenance"]["pantry_content_sha256"] = pantry.get("pantry_content_sha256")
    new["provenance"]["pantry_rows"] = pantry.get("rows_at_run_start")
    return new


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--only", action="append", default=[], help="Limit to a dimension (e.g. dimension3).")
    parser.add_argument(
        "--strict-data", action="store_true", help="Fail if the reference-data hashes differ."
    )
    parser.add_argument(
        "--summary-file", type=Path, help="Append the markdown report here (GITHUB_STEP_SUMMARY)."
    )
    parser.add_argument("--json-out", type=Path, help="Write the machine-readable report here.")
    parser.add_argument("--update", action="store_true", help="Refresh the baseline from this scorecard.")
    parser.add_argument("--reason", default="", help="Required with --update: why the baseline moves.")
    args = parser.parse_args(argv)

    try:
        scorecard = json.loads(args.scorecard.read_text())
        baseline = json.loads(args.baseline.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"GATE ERROR: cannot read the scorecard or the baseline: {exc}", file=sys.stderr)
        return 2

    if scorecard.get("aborted"):
        print(
            "GATE ERROR: this run was ABORTED by the infrastructure circuit breaker and was never scored: "
            f"{scorecard.get('abort_reason')}. The gate will not compare against it or record it as a "
            "baseline.",
            file=sys.stderr,
        )
        return 2

    if args.update:
        if not args.reason.strip():
            print("GATE ERROR: --update requires --reason", file=sys.stderr)
            return 2
        args.baseline.write_text(
            json.dumps(build_baseline_update(scorecard, baseline, args.reason), indent=2) + "\n"
        )
        print(f"baseline refreshed from {scorecard.get('run_id')}: review `git diff` before committing it")
        return 0

    report = compare(scorecard, baseline, only=set(args.only) or None, strict_data=args.strict_data)
    markdown = render_markdown(report, args.scorecard.name)
    print(markdown)
    if args.summary_file:
        with args.summary_file.open("a") as handle:
            handle.write(markdown + "\n")
    if args.json_out:
        args.json_out.write_text(
            json.dumps(
                {
                    "passed": report.passed,
                    "findings": [f.__dict__ for f in report.findings],
                    "notes": report.notes,
                },
                indent=2,
            )
        )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
