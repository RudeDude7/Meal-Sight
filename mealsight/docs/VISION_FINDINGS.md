# Vision Model Findings (Summary)

Full detail: `docs/vision_diagnostic_report.md` (single-sample diagnosis) and
`docs/vision_benchmark_report.md` (135-call benchmark, 3 reps/combo, temperature=0).

## Recommendation

Use **`mistral-medium-2505`** with the **conservative ("B") prompt** —
mean F1 0.64 across all 5 images (corrected scoring; see below). The
original vision call used `mistral-small-2603`, which scored F1 0.07 on the
same task — that model has a strong prior toward a generic "typical fridge"
(chicken thighs, bell peppers) regardless of what's actually in the photo.

## Why prompt A catastrophically fails on 2 images, but prompt B doesn't

Prompt A ("current") just asks for one item per line, with no required
delimiter. Prompt B/C require `<item> | confidence: <level>` — the pipe is
load-bearing.

On photo_01/02/05, `mistral-medium-2505` under prompt A returned clean lines
("Butter", "Onions", "Bananas"). On photo_03 and photo_04, the *same model,
same prompt* instead appended a location aside to nearly every line —
"Onions (in a container on the bottom shelf)", "Corn (in a container on the
second shelf)" — with no delimiter separating the item from the aside. Since
nothing marks where the item name ends, that trailing text became part of
the "item," and none of it matched ground truth anymore. Precision and
recall both landed at exactly 0.00 on those two images — a complete
formatting failure, not a content failure; the model had actually named
correct items in both. Prompts B and C don't have this failure mode because
the pipe delimiter protects the item name regardless of how much the model
decides to editorialize after it.

## Resolution sensitivity

Downscaling photo_01 measurably hurt accuracy with the best model/prompt:

| resolution | F1 |
|---|---|
| native (100%) | 0.67 |
| 50% scale | 0.52 |
| 25% scale | 0.43 |

Any image resizing in the ingestion pipeline should be treated as an
accuracy risk, not a free optimization.

## Dataset ceiling

Even the best (model, prompt, photo) combination only reached F1 ~0.77–0.79
— nothing approached 1.0. Some of that is a real model gap (`shrimp` and
`spinach` were never identified by any of the 3 models across any of the 15
runs per image where they appear). But some of it is a labeling artifact:
`aicook` applies a whole-fridge ingredient list to every photo of that
fridge, not a per-frame inventory, so items like `beef`, `ham`, and `shrimp`
in photo_01's ground truth are confirmed not actually visible in that frame.
We now track this explicitly in
`test_data/eval_cases/visibility_exclusions.csv` and report a
visibility-adjusted recall alongside raw recall — on photo_01 that raises
recall from 0.62 to 0.69. Treat the ~0.77 ceiling as roughly where this
dataset's labels stop being fair to the model, not as evidence the model
can't do better.

## Scoring methodology note

The benchmark's matcher was corrected mid-project (container-word
stripping, brand-name recognition, one-to-one bipartite assignment instead
of independent per-item lookups) — see "Scoring corrections" in
`vision_benchmark_report.md` for the full before/after. The best
configuration's mean F1 moved from 0.55 to 0.64 purely from fixing scoring
bugs, with zero new API calls — a reminder that eval harness bugs can look
identical to model problems until checked.
