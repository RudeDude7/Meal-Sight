# Continuous integration

Two workflows in `.github/workflows/` (the git root is the parent of `mealsight/`).

| Workflow | Runs | Secrets | API calls |
|---|---|---|---|
| `ci.yml` | every push and PR | none (placeholder env vars, not secrets) | none |
| `eval-nightly.yml` | **manual dispatch only; the nightly schedule is disabled** (see "Free-tier change") | `MISTRAL_API_KEY`, `GROQ_API_KEY`, `OPENWEATHER_API_KEY`, exposed to the one step that runs the suite | ~118 calls, ~426,000 tokens |

## ci.yml (three parallel jobs)
- **backend**: `ruff check .`, `mypy --strict mealsight eval`, `pytest`. (Tests are not yet mypy-clean; that is pre-existing debt.)
- **frontend**: `npm ci`, typecheck, lint, build.
- **matcher-gate**: builds the databases offline from the pinned recipe snapshot, runs Dimension 3, and compares it with the baseline (`--strict-data` also fails if the rebuilt reference data hashes differ from those the baseline was recorded on).

## Why the databases come from a snapshot
`*.db` files are gitignored and the recipe corpus is normally fetched live from TheMealDB, so a fresh runner has neither. `mealsight/seed/data/recipes_snapshot.json` (250 recipes, count + sha256 verified on load) makes the corpus reproducible. Refresh it with `python -m mealsight.seed.snapshot export`, then refresh the baseline, since Dimension 3's expectations are hand-derived against that data.

## Fresh-checkout seeding
A clean runner has no database files. Both the matcher-gate job and the nightly job build them the same way: `seed_all --from-snapshot` (recipes, synonyms, substitutions, nutrition), then `scripts/reset_demo_pantry.py`, which now applies all three schemas, loads the shelf-life reference table from its committed JSON, and seeds the pantry from `test_data/demo_pantry.json`. Result on a clean directory: 64 rows, content hash `c975c014058a`, the value recorded in the baseline. The gate compares that hash (`--strict-data`) for the pantry-dependent dimensions. The runner itself records an absent pantry (`pantry_present: false`, hash `null`) instead of raising, because Dimension 3 does not use a pantry; a pantry-dependent run against an absent pantry fails the gate.

## The regression gate (`eval/compare.py`, `eval/baseline/baseline.json`)
The suite legitimately fails overall (Dimension 1 at 0.488 vs 0.60, documented in `docs/EVALUATION.md`), so gating on the verdict would be permanently red. The gate enforces **regression** instead. It fails on: a missing dimension, a changed pass threshold, fewer cases, a score below baseline minus the per-dimension tolerance (Dimension 1: a band just wider than its observed 0.485–0.492 spread), a broken safety invariant (hard-constraint violations, matcher disagreements, case defects, real databases touched), or an unreadable scorecard/baseline (exit 2, never silently green). A known-failing dimension at its known level passes. Improvements are reported with a prompt to refresh.

Refresh the baseline deliberately: `python -m eval.compare eval/results/run_X.json --update --reason "why"`, then review `git diff`. Tolerances, statuses and invariants are preserved by the refresh.

## Secrets and cost
Keys are GitHub secrets, set only on the steps that need them (preflight, suite), never echoed. Fork PRs never receive them, and the PR workflow uses none.

## Free-tier change: why the nightly is disabled
Mistral restructured its free tier mid-project. Measured from live `x-ratelimit` headers on 2026-11-07, `ministral-8b-2512` is **2 requests/minute (0.033 RPS) and 40,000 tokens/minute**; the Phase 1 console reading, which the limiter had been using, was 3.13 RPS and 625,000 TPM. A full run makes ~118 calls, which at 2 a minute is about an hour of rate-limit waiting alone, longer than the job timeout. So `eval-nightly.yml` keeps its manual `workflow_dispatch` trigger and loses its `schedule`. This is a provider change, not a defect in the suite or the pipeline.

**Cost picture.** A full run is ~426,000 tokens, which is about 4 cents against the account's $10 monthly included allowance (pay-as-you-go is disabled, so no charge is possible). Tokens are not the constraint; **throughput is**. A manual dispatch fails the preflight in seconds while the key allows fewer than 10 requests/minute (the `min_rpm` input can lower that, at the price of a very long run and a raised step timeout).

**Still on every PR:** Dimension 3 (no API calls, under a second) in `ci.yml`, a real regression gate on matcher arithmetic.

**To re-enable:** when `python -m eval.preflight` shows 10+ requests/minute, restore `schedule: - cron: "17 3 * * *"` under `on:` in the workflow.

## Flaky test
`test_ws_mid_run_receives_buffered_then_live_messages` was sleep-timed. It is now synchronised with `threading.Event`s (no timing assumption), so it is deterministic rather than retried. No automatic retries are used anywhere in the pipeline.

## Preflight, circuit breaker, timeouts (manual eval run)
- **Preflight** (`python -m eval.preflight`, 3-minute step timeout): one trivial call per provider, printing the HTTP status and rate-limit headers, plus each key's length and whether it has leading/trailing whitespace. Never prints a key. Fails the job in seconds on 429, 401/403, 5xx, unreachable, or a key allowed fewer than 10 requests/minute (a full run needs about 9). Settings also strips whitespace from secrets at load time.
- **Circuit breaker** (`eval/circuit.py`): within a dimension, once at least 5 provider calls have finished, if 50% or more failed after retries (429, provider error, rejected key) the run is ABORTED: the scorecard records `aborted: true` and the reason, the suite exits 3, the job fails, and `eval.compare` refuses the scorecard (exit 2, also for `--update`). An outage is never recorded as a quality score.
- **Timeouts**: suite step 30 minutes (a real run is 11-17), job 40.
