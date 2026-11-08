"""Dimension 1 — ingredient recognition. Calls the real, deployed
mealsight.perception.processor.analyze_fridge_photo() once per photo —
same model, same prompt, same provider-layer rate limiting/retry, same
canonicalization the production pantry-scan flow actually uses — over
every photo in test_data/images/ that image_ground_truth.csv has ground
truth for (30 photos, not the 5-image dev subset scripts/benchmark_
vision.py explored). analyze_fridge_photo is read-only (pantry_db is
only ever used to load the shelf-life map), so this makes zero writes
to the real pantry.

Scoring reuses eval.matching verbatim — the same bipartite matcher,
synonym handling, and visibility adjustment scripts/benchmark_vision.py
already validated. Nothing here re-derives that methodology.
"""

from __future__ import annotations

import time

from eval.circuit import breaker
from eval.matching import IMAGES_DIR, load_ground_truth_all, mean, score_image
from eval.models import DimensionResult, ImageResult
from mealsight.config.settings import settings
from mealsight.db import get_pantry_db, get_recipe_db
from mealsight.matching.synonyms import load_synonym_map
from mealsight.perception.processor import analyze_fridge_photo
from mealsight.perception.prompt import VISION_PERCEPTION_PROMPT
from mealsight.providers import get_text_provider
from mealsight.utils.logging import bind_trace_id

NAME = "dimension1_ingredient_recognition"
PASS_THRESHOLD = 0.60  # measured dev baseline was F1 0.64; set just under it


def aggregate_images(image_results: list[ImageResult]) -> dict[str, float]:
    # A photo is scorable whenever it has ground truth. A photo where the
    # model identified nothing is a real zero and must stay in the mean;
    # only harness failures (missing file, exception), which carry no
    # ground truth, are left out.
    scored_results = [r for r in image_results if r.ground_truth_items]
    return {
        "precision": mean([r.precision for r in scored_results]),
        "recall_raw": mean([r.recall_raw for r in scored_results]),
        "recall_adjusted": mean([r.recall_adjusted for r in scored_results]),
        "f1_raw": mean([r.f1_raw for r in scored_results]),
        "f1_adjusted": mean([r.f1_adjusted for r in scored_results]),
        "images_scored": len(scored_results),
    }


async def run_dimension1(case_limit: int | None = None) -> DimensionResult:
    photo_ids = sorted(load_ground_truth_all().keys())
    if case_limit is not None:
        photo_ids = photo_ids[:case_limit]

    pantry_db = get_pantry_db()
    recipe_db = get_recipe_db()
    synonym_map = await load_synonym_map(recipe_db)

    image_results: list[ImageResult] = []
    api_calls = 0
    total_tokens = 0
    start = time.monotonic()

    breaker.start(NAME)
    for photo_id in photo_ids:
        breaker.check()
        image_path = IMAGES_DIR / f"{photo_id}.jpg"
        if not image_path.exists():
            image_results.append(
                ImageResult(
                    photo_id=photo_id,
                    predicted_items=[],
                    ground_truth_items=[],
                    precision=0.0,
                    recall_raw=0.0,
                    recall_adjusted=0.0,
                    f1_raw=0.0,
                    f1_adjusted=0.0,
                    error=f"image file not found: {image_path}",
                )
            )
            continue

        image_bytes = image_path.read_bytes()
        trace_id = f"eval-dimension1-{photo_id}"
        bind_trace_id(trace_id)
        try:
            perception = await analyze_fridge_photo(
                image_bytes,
                pantry_db=pantry_db,
                recipe_db=recipe_db,
                synonym_map=synonym_map,
            )
            api_calls += 1
            total_tokens += sum(
                int(call.get("total_tokens", 0))
                for call in get_text_provider().get_call_log()
                if call.get("trace_id") == trace_id
            )
            predicted_items = [item.name for item in perception.identified_items]
            scored = score_image(photo_id, predicted_items)
            image_results.append(
                ImageResult(
                    photo_id=photo_id,
                    predicted_items=predicted_items,
                    ground_truth_items=scored.ground_truth,
                    precision=scored.precision,
                    recall_raw=scored.recall_raw,
                    recall_adjusted=scored.recall_adjusted,
                    f1_raw=scored.f1_raw,
                    f1_adjusted=scored.f1_adjusted,
                    error=perception.notes if not perception.identified_items else None,
                )
            )
        except Exception as exc:  # analyze_fridge_photo itself never raises; this guards the eval harness
            image_results.append(
                ImageResult(
                    photo_id=photo_id,
                    predicted_items=[],
                    ground_truth_items=[],
                    precision=0.0,
                    recall_raw=0.0,
                    recall_adjusted=0.0,
                    f1_raw=0.0,
                    f1_adjusted=0.0,
                    error=str(exc),
                )
            )

    breaker.check()
    breaker.stop()
    wall_clock = time.monotonic() - start

    aggregate = aggregate_images(image_results)
    precision = float(aggregate["precision"])
    recall_raw = float(aggregate["recall_raw"])
    recall_adjusted = float(aggregate["recall_adjusted"])
    f1_raw = float(aggregate["f1_raw"])
    f1_adjusted = float(aggregate["f1_adjusted"])
    return DimensionResult(
        name=NAME,
        pass_threshold=PASS_THRESHOLD,
        score=f1_adjusted,
        passed=f1_adjusted >= PASS_THRESHOLD,
        metrics={
            "precision": precision,
            "recall_raw": recall_raw,
            "recall_adjusted": recall_adjusted,
            "f1_raw": f1_raw,
            "f1_adjusted": f1_adjusted,
            "vision_model": settings.VISION_MODEL,
            "prompt_char_len": len(VISION_PERCEPTION_PROMPT),
            "images_scored": aggregate["images_scored"],
            "images_total": len(photo_ids),
        },
        case_count=len(photo_ids),
        api_calls=api_calls,
        total_tokens=total_tokens,
        wall_clock_seconds=wall_clock,
        image_results=image_results,
    )
