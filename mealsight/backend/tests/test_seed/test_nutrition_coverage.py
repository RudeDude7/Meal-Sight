"""Guards mealsight/seed/data/nutrition_data.json's coverage of both
populations that actually need it: the seeded recipe corpus, and the
vision model's own ingredient vocabulary.

Phase 2.2 verification found nutrition coverage at only 25.6% distinct /
74.4% occurrence-weighted, discovered only because someone happened to
look past the top-20 uncovered list. That gap was closed — but a second,
separate gap was found afterward: "white rice" had no nutrition row even
though the *recipe*-corpus coverage figure had already reached 100%,
because that figure only ever measured ingredient strings appearing in
TheMealDB recipe text. The vision model produces its own vocabulary
("white rice", "chicken thigh", "scallions") that never appears in
TheMealDB at all, so a recipe-corpus-only coverage check can silently
miss real, common vision-vocabulary gaps. This test checks both
populations separately so a future regression in either — a new recipe
ingredient nutrition_data.json doesn't cover, or a vision prompt change
that introduces new vocabulary the synonym table doesn't resolve — fails
loudly here instead of silently degrading nutrition accuracy downstream.

Both checks deliberately verify the real, already-seeded recipes.db
(and, for the vision check, the real checkpointed benchmark output on
disk if present) rather than a synthetic fixture — the same reasoning
test_substitutions_safety.py and test_synonyms_distinctness.py use for
checking the real substitutions/synonyms JSON files rather than a
fixture standing in for them.
"""

from __future__ import annotations

import pytest

from mealsight.config.settings import settings
from mealsight.db import get_recipe_db
from mealsight.seed.load_nutrition import coverage_report, vision_vocabulary_coverage_report
from mealsight.seed.vision_vocabulary import (
    VISION_BENCHMARK_CHECKPOINT_PATH,
    extract_vision_ingredient_names,
)

MIN_RECIPE_CORPUS_WEIGHTED_COVERAGE_PCT = 90.0

# Set below the recipe-corpus threshold, deliberately: a meaningful chunk
# of real vision-benchmark output is inherent hedging/uncertainty noise
# from weaker prompt variants under test ("red with content unclear",
# "what appear to be red sauce or puree", brand-name label misreads like
# "Chavroux cheese") that no synonym table or nutrition row can sensibly
# resolve — see docs/KNOWN_ISSUES.md and the Phase 2.2 vision-coverage
# session notes. 80% is comfortably below the real measured baseline
# (85.6% at the time this test was written) while still catching a
# genuine regression.
MIN_VISION_VOCABULARY_WEIGHTED_COVERAGE_PCT = 80.0

pytestmark = pytest.mark.skipif(
    not settings.recipes_db_path.exists(),
    reason="recipes.db has not been seeded yet — run `mealsight-seed` first",
)


async def test_recipe_corpus_occurrence_weighted_coverage_stays_above_90_percent() -> None:
    db = get_recipe_db()
    try:
        report = await coverage_report(db)
        assert report["weighted_coverage_pct"] >= MIN_RECIPE_CORPUS_WEIGHTED_COVERAGE_PCT, (
            f"recipe-corpus occurrence-weighted nutrition coverage dropped to "
            f"{report['weighted_coverage_pct']}% (covered {report['covered_occurrences']}/"
            f"{report['total_occurrences']} ingredient occurrences) — add nutrition_data.json "
            f"entries for the newly uncovered ingredients: {report['top_uncovered']}"
        )
    finally:
        await db.close()


@pytest.mark.skipif(
    not VISION_BENCHMARK_CHECKPOINT_PATH.exists(),
    reason=f"no vision benchmark checkpoint at {VISION_BENCHMARK_CHECKPOINT_PATH} — run "
    "scripts/benchmark_vision.py first",
)
async def test_vision_vocabulary_occurrence_weighted_coverage_stays_above_80_percent() -> None:
    db = get_recipe_db()
    try:
        raw_vision_names = extract_vision_ingredient_names()
        report = await vision_vocabulary_coverage_report(db, raw_vision_names)
        assert report["weighted_coverage_pct"] >= MIN_VISION_VOCABULARY_WEIGHTED_COVERAGE_PCT, (
            f"vision-vocabulary occurrence-weighted nutrition coverage dropped to "
            f"{report['weighted_coverage_pct']}% (covered {report['covered_occurrences']}/"
            f"{report['total_occurrences']} ingredient occurrences) — either add "
            f"ingredient_synonyms.json / nutrition_data.json entries for the newly uncovered "
            f"vocabulary, or confirm it's genuinely unresolvable prompt-hedging noise: "
            f"{report['top_uncovered']}"
        )
    finally:
        await db.close()
