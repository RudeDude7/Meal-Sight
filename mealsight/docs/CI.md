# Continuous integration

Two workflows in `.github/workflows/` (the git root is the parent of `mealsight/`).

| Workflow | Runs | Secrets | API calls |
|---|---|---|---|
| `ci.yml` | every push and PR | none (placeholder env vars, not secrets) | none |
| `eval-nightly.yml` | 03:17 UTC daily + manual dispatch | `MISTRAL_API_KEY`, `GROQ_API_KEY`, `OPENWEATHER_API_KEY`, exposed to the one step that runs the suite | ~118 calls, ~426,000 tokens |

## ci.yml (three parallel jobs)
- **backend**: `ruff check .`, `mypy --strict mealsight eval`, `pytest`. (Tests are not yet mypy-clean; that is pre-existing debt.)
- **frontend**: `npm ci`, typecheck, lint, build.
- **matcher-gate**: builds the databases offline from the pinned recipe snapshot, runs Dimension 3, and compares it with the baseline (`--strict-data` also fails if the rebuilt reference data hashes differ from those the baseline was recorded on).

## Why the databases come from a snapshot
`*.db` files are gitignored and the recipe corpus is normally fetched live from TheMealDB, so a fresh runner has neither. `mealsight/seed/data/recipes_snapshot.json` (250 recipes, count + sha256 verified on load) makes the corpus reproducible. Refresh it with `python -m mealsight.seed.snapshot export`, then refresh the baseline, since Dimension 3's expectations are hand-derived against that data.

## The regression gate (`eval/compare.py`, `eval/baseline/baseline.json`)
The suite legitimately fails overall (Dimension 1 at 0.488 vs 0.60, documented in `docs/EVALUATION.md`), so gating on the verdict would be permanently red. The gate enforces **regression** instead. It fails on: a missing dimension, a changed pass threshold, fewer cases, a score below baseline minus the per-dimension tolerance (Dimension 1: a band just wider than its observed 0.485–0.492 spread), a broken safety invariant (hard-constraint violations, matcher disagreements, case defects, real databases touched), or an unreadable scorecard/baseline (exit 2, never silently green). A known-failing dimension at its known level passes. Improvements are reported with a prompt to refresh.

Refresh the baseline deliberately: `python -m eval.compare eval/results/run_X.json --update --reason "why"`, then review `git diff`. Tolerances, statuses and invariants are preserved by the refresh.

## Secrets and cost
Keys are GitHub secrets, set only on the step that runs the suite, never echoed. Fork PRs never receive them, and the PR workflow uses none. Nightly volume is ~426k tokens (~12.8M/month). Against the one known limit (ministral-8b-2512: 625,000 tokens/min, 3.13 req/s) a run uses roughly 4-6% of the per-minute budget. The monthly allowance on the free plan is not documented in this repo, so the real headroom is unknown. If development quota gets tight, change the cron to weekly or run `python -m eval dimension2 --sampled` instead.

## Flaky test
`test_ws_mid_run_receives_buffered_then_live_messages` was sleep-timed. It is now synchronised with `threading.Event`s (no timing assumption), so it is deterministic rather than retried. No automatic retries are used anywhere in the pipeline.
