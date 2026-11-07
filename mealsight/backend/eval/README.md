# MealSight eval

Run from `backend/`: `PYTHONPATH=. .venv/bin/python -m eval [dimension1] [dimension2] [--limit N] [--sampled]`.
Every run writes one JSON scorecard to `eval/results/` and records model ids, prompt hashes, git commit
(plus whether the working tree was dirty and a hash of the uncommitted changes), a timestamp, and the
pantry fixture hash.

Before a run, reset the pantry so every run starts from identical conditions:
`PYTHONPATH=. .venv/bin/python ../scripts/reset_demo_pantry.py` (no API calls; backs up first).

## Dimensions implemented

- **Dimension 1, ingredient recognition.** Real `analyze_fridge_photo` over all 30 photos, scored by
  `eval/matching.py` against `test_data/eval_cases/image_ground_truth.csv`. Pass threshold F1 0.60.
- **Dimension 2, constraint satisfaction.** 30 natural-language cases through the full pipeline. Hard
  constraints (dietary, cook time, servings, avoid lists) are binary and checked against the
  hand-authored constraints in `eval/cases.py` as well as what the pipeline extracted. Soft constraints
  (cuisine; protein when a case sets one) are scored separately against their own threshold (0.5). Honest
  refusal passes only on cases authored as unsatisfiable; a satisfiable request that is refused fails.

## What the Dimension 1 headline figure does and does not measure

The vision benchmark (`scripts/benchmark_vision.py`, prompts A-current / B-conservative / C-grounded)
sends the original **pipe-delimited** prompt format (`item | confidence: ... | location: ...`). The
production prompt (`mealsight/perception/prompt.py::VISION_PERCEPTION_PROMPT`) is the **JSON-extended
variant** of B-conservative: same wording and the same "say so if you cannot identify anything" permission,
but asking for a JSON object with quantity, unit and freshness per item.

**The two have not been compared directly.** The prompt-selection result (B ranks first, within noise of C,
about 0.06 ahead of A on ministral-8b-2512) comes from the pipe-delimited format. The Dimension 1 figure in
the scorecard is measured on the production JSON prompt, so it is a near-neighbour of what the benchmark
selected, not the same prompt. A format effect, in either direction, is possible and unmeasured.

## Scorer corrections that make older figures non-comparable

The earlier Dimension 1 figures (F1 0.64 on mistral-medium-2505, 0.55 on ministral-8b-2512) are
superseded: a photo where the model identifies nothing now counts as zero rather than being dropped, and
"green onion" no longer matches "onion". Both can only lower a score. Dimension 2 enforces authored
constraints, whole-word avoid matching, and a verdict that requires every case to pass.

## Scorer fixtures

`tests/test_eval/test_scorer_fixtures.py` holds known-answer cases (exact 1.0, exact 0.0, near-misses,
honest refusal passes, dietary violation fails) that the scorers must pass before any number is trusted.

## Dimension 2 findings and corrections (2026-11-06)

First full run: `run_1793926853` (20 of 30 passed, 0 violations, 10 refusals). Diagnosis and
follow-up changes, kept here so the history does not have to be reconstructed:

- **Profile cook-time default was enforced as a hard cap.** `preferred_cook_time_minutes` (30,
  `DEFAULT_PROFILE_VALUES`, never written by the user) was copied into the request and sent to
  search as a filter. `UnifiedMealRequest.max_cook_time_is_default` now records provenance; only a
  stated limit filters (and the scorer enforces only stated limits). A default only nudges ranking
  (`DEFAULT_TIME_FIT_WEIGHT`).
- **Search relaxed only on an empty set, not on "nothing cookable".** Cuisine and the system's
  meal-type guess now relax when no candidate can be cooked from the pantry. Dietary restrictions and
  a stated cook time never relax on that path.
- **Three authored expectations were wrong** (d2_10, d2_12, d2_30). Corrected in
  `eval/cases.py::CORRECTIONS` with the reason; the first run's scorecard keeps the originals.
  d2_10 had "passed" a refusal for the wrong reason.
- **Extraction filed "nut-free" under `avoid_ingredients` instead of `dietary_restrictions`.** Measured
  before the fix (10 reps per case, temperature 0, post-normalization): nut-free present in
  `dietary_restrictions` in 0/10 (d2_05), 0/10 (d2_09), 3/10 (d2_10) and 10/10 (d2_15); every other restriction
  (vegan, vegetarian, gluten-free, dairy-free) 10/10 in every case. In the failing runs the restriction was
  not lost, it moved to `avoid_ingredients=["nut"]`, and **nothing in the single-request pipeline
  enforced `avoid_ingredients`** (prompt text only). Fixed in two layers: `mealsight/matching/avoid.py`
  excludes recipes in code (whole-word, allergen groups), and `mealsight/perception/restrictions.py`
  unions pattern-detected restrictions into the model's output. After the fix nut-free is present
  10/10 in every case. See the guarantee and its limits in the restrictions module docstring.
- The eval's own `AVOID_GROUPS` stays a separate copy of the production one on purpose, so the scorer
  is an independent check on the filter and not a mirror of it.

## Default cook-time nudge and cuisine cases (2026-11-06)

**Nudge weight.** 14 requests that state no time (profile default 30 min), full pipeline, weights
interleaved per request. Selection rule fixed before running: the smallest weight at which >=80% of top-ranked
recipes fall within the preference, with no more than 0.25 of match score given up and every pick cookable.

| weight | top-ranked within 30 min | final pick within 30 min | top-1 changed vs 0.0 | max / mean match given up |
|---|---|---|---|---|
| 0.00 | 0/14 | 3/14 | 0 | 0.00 / 0.000 |
| 0.05 | 1/14 | 7/14 | 1 | 0.08 / 0.006 |
| 0.15 | 13/14 | 8/14 | 13 | 0.11 / 0.067 |
| 0.25 | 13/14 | 7/14 | 13 | 0.11 / 0.067 |

Chosen: **0.15**. Two caveats recorded honestly: (1) the first sweep was invalid. `_composite_score` was being
rebuilt for the repetition-checked top candidates WITHOUT the time term, so the nudge vanished for exactly those
recipes, and the sweep script patched the function object instead of the module. Both fixed, with a regression
test. (2) The weight controls the RANKING, not the final recommendation: the reasoning model makes the final pick
and followed the ranking only partly (final pick within 30 min: 57% at 0.15). Adding soft cook-time wording to the
reasoning prompt did not change that (15/28 over two repetitions), so it was reverted. Making the default govern
the final pick would mean choosing the top cookable candidate in code and using the model only to explain; that is
an architecture change and has not been made.

**Cuisine cases.** Ten cases (d2_31 to d2_40) added after the first run, labelled attainable or not against the
cookable list before being run. The headline soft score is the hit rate over cases where the seeded pantry can
cook a recipe of the cuisine; unattainable ones exercise the honest-miss path and are reported separately.

## Cuisine label fix (2026-11-06)

Search matched cuisine by exact string, but the corpus mixes country names (India, France, Netherlands, United
States) with demonyms (the other 20). "Indian" and "French" matched nothing, and the reasoning layer then claimed
"None of the candidates is Indian cuisine" while Chicken Handi was cookable. All cuisine comparisons (search, the
soft scorer, the reasoning facts) now go through `mealsight/matching/cuisine.py`; every one of the 24 corpus
labels has a family (country, demonym, variants), matching is case-insensitive and works in both directions, and
a real-corpus test fails if a seeded label has no family.

Soft cuisine score, before and after: run_1793975487 (before) headline 0.857 (6/7 attainable) but d2_33's hit was
luck (cuisine had been dropped, and the pick happened to be French), so the real rate was 5/7 = 0.714; pooled 0.5.
run_1793976350 (after, 3 more cases) headline 1.0 (9/9 attainable), pooled 0.6 (9/15); all 6 unattainable cases
are honest misses. Three cases added (d2_41 to d2_43, one per name form still untested).

## Dietary restrictions with no corpus tag (2026-11-06)

12 of the 17 restrictions in the extraction vocabulary have no tag in the recipe corpus, and search applied each as
a hard tag filter, so a request carrying one matched nothing and was refused (`dietary_filters=["peanut_free"]` ->
0 recipes; nut_free -> 222). `mealsight/matching/diet.py` now classifies every restriction into exactly one of:
tag-backed (vegetarian, vegan, dairy-free, gluten-free, nut-free), ingredient-enforced (peanut-free, shellfish-free,
soy-free, egg-free, pescatarian, halal, kosher), or unenforced (low-sodium, low-fat, low-carb, keto, paleo). An import-time
assertion fails if the extraction vocabulary and these groups ever differ.

- halal and kosher are PARTIAL: pork/alcohol (halal) and pork/shellfish/meat-with-dairy (kosher) are excluded; slaughter
  and certification cannot be verified from a recipe, and the answer says so. The scorer fails the case if it does not.
- The nutritional restrictions are declined, not filtered: over all 250 recipes calculate_nutrition has >80% ingredient
  coverage for 189, but the figures come from rough unit conversions and are wrong even there (Kumpir, a baked-potato dish,
  13 g carbs per serving and tagged low_carb; Creamy Tomato Soup 241 g; sodium 6 mg to 33,192 mg; median fat 60 g).
  They are disclosed as "NOT ENFORCED" instead.
- Cases d2_44 to d2_55 added after this fix. d2_06 (keto) expectation changed from refusal to recommendation-with-
  disclosure, recorded in cases.py CORRECTIONS.

## Dimension 3: match accuracy (2026-11-06)

30 cases (`eval/cases3.py`) whose expected outcomes were derived by hand from the recipe rows, the synonym and
substitution tables and the matcher's documented rules, never from running the matcher. The harness runs the
production `match_recipe_by_id` and compares the numeric score (tolerance 0.001) and the per-ingredient
classification (exact multisets of canonical names) SEPARATELY; a case passes only if both are right, plus can_cook
and avoid-list exclusion. No API calls.

First run (run_1793982333): 27/30, three disagreements. d3_13 and d3_19 were my derivation error (I treated "cube" as a
stripped container word; it is not in the list), corrected in `cases3.py` with a note. d3_28 ("Garlic Clove" with garlic in
the pantry) is a real matcher defect: it reports garlic missing, which affects 25 of 250 recipes. d3_07 was later replaced
(its protected-term logic could not fail, see the mutation check). Provenance now also records the extraction prompt,
the lexicons/rule sets/weights (`component_versions`) and the reference tables (`data_versions`), see `eval/provenance.py`.

## Dimension 3 follow-up (2026-11-06)

- `match_rank` and the search viability probe called the matcher without the user's dietary restrictions or avoid list, so
  the matcher's rejection of a forbidden substitute never ran in the live pipeline (a dairy-free user with Greek yogurt in the
  pantry was offered it for mayonnaise). Both now pass them; the matcher also judges substitutes against ingredient-enforced
  restrictions (peanut-free, pescatarian, halal ...) by ingredient rules, not by a corpus tag that does not exist, and refuses
  a substitute containing an avoided ingredient. A restriction the system cannot verify never vetoes a substitute.
- Fused unit/form names found by auditing all 495 distinct normalized ingredient names, now synonyms of their base: garlic
  clove, basil leaf, tarragon leaf, fennel bulb, mozzarella ball, chicken/vegetable stock cube. Deliberately NOT collapsed:
  bay leaf, cinnamon stick, lemon juice/zest, orange zest, gelatine leaf (different things).
- Dimension 3 now has 32 cases (d3_31, d3_32 cover stock cube vs stock in both directions). Run: run_1793991757, 32/32.

## Dimensions 4 and 5 (2026-11-06)

**Isolation.** Each case runs against a throwaway pantry and profile database (`eval/isolation.py`): the three MCP
servers are pointed at temp files through `MCPClientManager(env=...)`, the files are recreated from the real schema
before every case, and the table row counts are asserted zero (`reset()` raises otherwise). Seeded state is read back
through the servers' own read functions and compared with the request (`verify_pantry`, `verify_profile`). The real
pantry, user and recipe database files are SHA-256 fingerprinted before and after each dimension and must be
unchanged (`real_data_untouched`).

**Dimension 4 (freshness, 15 cases, threshold 0.80).** A case fails only if a cookable recipe used an expiring, usable
item and the recommendation neither used one nor was correctly out-scored by a hand-computed composite. Items more than
2 days past shelf life are waste and must not be reported as opportunities. First run run_1793993547: 12/15, of which d4_13
was a bug in my case-construction helper (butter is a staple, so asking for it to expire left it fresh); the harness caught it
as a case defect. Corrected run run_1793993811: 13/15. Both failures (d4_06, d4_09) are the reasoning step overriding a
correct ranking: match_rank put the expiring-item recipe first (composites 0.705 and 0.552, equal to the hand values) and the
model then chose Kumpir "for its cook time". One mechanism fault: the freshness flag is not set when the pantry item and the
recipe line differ in name (d4_08, chicken thigh vs "chicken"); it did not change that outcome.

**Dimension 5 (personalization, 15 cases, threshold 0.80).** Recipe pairs that tie exactly under default scoring, each
used with opposite profiles where possible. First run run_1793997836: 9/15; the corrected harness (a dislike case's default
best is the disliked recipe by design, which my first defect check wrongly rejected) gave run_1793999325: 11/15. Findings: learned
cuisine preferences have NO effect on ranking (`_cuisine_score` lowercases the cuisine but profile keys keep their logged
capitalisation); the profile's `protein_preference` is neither merged into the request nor shown to the model; stored
dislikes are enforced only by the model reading a prompt line; a profile `dietary_restrictions` entry is ignored entirely
(probe, not scored). `passed_without_scoring_support` lists passes that came from tie-breaking.

**Combined five-dimension run, run_1794000391 (2026-11-06): overall FAIL.** D1 0.489 (threshold 0.60) FAIL; D2 55/55 PASS;
D3 32/32 PASS; D4 14/15 = 0.933 PASS; D5 11/15 = 0.733 (threshold 0.80) FAIL. Dimension 4 is not stable between runs, because
the final pick is a language-model choice: across the three runs its failures were {d4_06, d4_09}, {d4_06, d4_09} and {d4_13},
each time the model overriding a ranking that put the expiring-item recipe first. Dimension 5's failures were identical in both
of its runs (d5_01, d5_03, d5_06, d5_07).

## Profile-application fixes (2026-11-07)

Dimension 5 had found that parts of the saved profile never reached the pipeline. Fixed, and audited field by field:
saved `dietary_restrictions` are now unioned with the request in fusion (so they take the same search, ingredient-rule,
substitute and explanation path as a stated restriction, in the recommendation pipeline and the meal planner); saved
`disliked_ingredients` are enforced in code by `match_rank` (a recipe containing one is left out while another cookable
option remains, and kept, flagged and disclosed, when it would otherwise leave nothing); learned cuisine scores are keyed by
canonical cuisine label where they are stored (`scoring.py`) and read (`profile.py`) and looked up by cuisine family
(`lookup_cuisine_score`), which also merges legacy spellings with no migration; `protein_preference` is merged into the request as
a default a stated protein overrides; and the freshness flag compares canonical forms and honours specificity. `cooking_skill`
and `budget_sensitivity` still reach only the model as prompt text, and the learned protein scores are still not read by ranking.
Dimension 5 gained d5_16 to d5_18 (recorded in `cases5.py`; the original 15 are unchanged), 18 cases at the same 0.80 threshold.
