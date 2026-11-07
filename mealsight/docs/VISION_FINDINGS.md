# Vision Model Findings (Summary)

Full detail: `docs/vision_diagnostic_report.md` (single-sample diagnosis) and
`docs/vision_benchmark_report.md` (135-call benchmark, 3 reps/combo, temperature=0).

> **Status update, 2026-10-16:** the recommendation below (`mistral-medium-2505`)
> is historical. That model was retired by Mistral and the medium tier is no
> longer reachable on this account's free plan; the live choice is now
> **`ministral-8b-2512`** (F1 0.55). The original text is kept below, but two
> of its findings were weakened or invalidated by a scoring defect found the
> same day: the "prompt A catastrophically fails" section and the resolution
> table are marked inline. The deprecation, the replacement benchmark, the
> scorer correction and a claim-by-claim audit are in "Update 2026-10-16" at
> the end of this file.

## Recommendation

Use **`mistral-medium-2505`** with the **conservative ("B") prompt** —
mean F1 0.64 across all 5 images (corrected scoring; see below). The
original vision call used `mistral-small-2603`, which scored F1 0.07 on the
same task — that model has a strong prior toward a generic "typical fridge"
(chicken thighs, bell peppers) regardless of what's actually in the photo.

## Why prompt A catastrophically fails on 2 images, but prompt B doesn't

> **CORRECTION 2026-10-16: this finding was substantially a scoring
> artifact. The text below is the original, left in place.**
> The "0.00 F1" on photo_03 and photo_04 was produced by the benchmark
> matcher, not by the model. The matcher did not strip parenthetical
> qualifiers, so "Onions (in a container on the bottom shelf)" could never
> equal ground truth "onion". The model had named the right items, as the
> original text itself says ("the model had actually named correct items in
> both"); the matcher then discarded them. With the matcher corrected,
> and scoring the identical stored responses:
>
> | mistral-medium-2505, prompt A | photo_03 F1 | photo_04 F1 | mean F1, all 5 photos |
> |---|---|---|---|
> | original matcher | 0.00 | 0.00 | 0.313 |
> | corrected matcher | 0.66 | 0.66 | 0.594 |
>
> Prompt A (0.594) vs prompt B (0.640) is a gap of about **0.05, not 0.33**,
> inside the roughly 0.08–0.11 run-to-run spread. B-conservative is still the
> best prompt, but "the pipe delimiter protects the item name" is no longer
> supported as the explanation of a catastrophic failure, because there was
> no catastrophic failure. The conclusion that B is the better prompt
> survives; the claimed magnitude and mechanism do not.

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

> **Re-checked 2026-10-16 (partially holds).** These F1 values came from
> `scripts/diagnose_vision.py`'s own simpler scorer, on a single sample per
> resolution, not from the benchmark matcher. Re-scoring the same three raw
> outputs (printed in `docs/vision_diagnostic_report.md`) with the validated
> matcher gives native 0.58, 50% 0.41, 25% 0.43 (visibility-adjusted 0.64,
> 0.46, 0.48). So native resolution is clearly better than either downscale
> (the actionable conclusion stands), but the figures differ and the
> "0.67 -> 0.52 -> 0.43" progression is not monotone under the validated
> matcher. With n=1 per row, treat the table as direction only.

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

> **Re-checked 2026-10-16 (holds).** With the corrected matcher the best
> per-image F1 is 0.67, 0.67, 0.79, 0.71, 0.79 (photo_01 to photo_05), so the
> "about 0.77–0.79" ceiling still describes the best photos, and `shrimp` and
> `spinach` are still never identified by any model on any photo.

## Scoring methodology note

The benchmark's matcher was corrected mid-project (container-word
stripping, brand-name recognition, one-to-one bipartite assignment instead
of independent per-item lookups) — see "Scoring corrections" in
`vision_benchmark_report.md` for the full before/after. The best
configuration's mean F1 moved from 0.55 to 0.64 purely from fixing scoring
bugs, with zero new API calls — a reminder that eval harness bugs can look
identical to model problems until checked.

It happened a second time: the parenthetical defect described in the 2026-10-16
update below moved a (model, prompt) average by up to 0.28 F1 with no new API calls.


## Update 2026-10-16: model retired, scorer and parser corrected, replacement measured

Everything above was measured on 2026-08-22 and is left as written, apart from
the inline correction notes. This section records what happened afterwards, in
order, including a mistake in the first version of the scorer fix.

### 1. mistral-medium-2505 was retired; the medium tier became unavailable

- **2026-09-04 (first observed):** live calls to `mistral-medium-2505` returned
  HTTP 429 with `x-ratelimit-limit-req-minute: 0`. A limit of zero is a quota,
  not a throttle, and it did not recover with waiting or retrying.
- **2026-10-16:** `mistral-medium-2505` is absent from the account's
  `/v1/models` list (retired). Every other model above the ministral family
  also returns 0 requests/minute on this account's free plan, so the medium
  tier is unavailable, not just the old pinned version. The account owner
  confirmed the console Limits page agrees with the API.

Limits read from live response headers on 2026-10-16:

| model | TPM | RPS | status |
|---|---|---|---|
| mistral-medium-2604 | n/a | 0 | 429 on every call |
| mistral-medium-latest | n/a | 0 | 429 on every call |
| mistral-small-2603 | n/a | 0 | 429 on every call |
| magistral-medium-latest | n/a | 0 | 429 on every call |
| ministral-14b-2512 | 937,500 | 0.50 (30/min) | works |
| ministral-8b-2512 | 625,000 | 3.13 (188/min) | works |

The retired model had 375,000 TPM / 0.42 RPS. `mistral-medium-2604`, its direct
successor, could not be benchmarked at all.

### 2. The scorer defect: parenthetical qualifiers

The matcher did not strip parenthetical qualifiers, so "potatoes (peeled)"
failed to match ground truth "potato" and "Onions (in a container on the bottom
shelf)" failed to match "onion". `normalize_words` now removes parentheticals
before matching (an unclosed "(" strips to end of string). No ground-truth row
contains a parenthesis, so only predictions are affected. No synonym entries
were added. The fix is in `scripts/benchmark_vision.py` and its port in
`backend/eval/matching.py`, with regression tests in `tests/test_eval/`.

**A mistake in my first version of this fix, caught by the audit.** Stripping
parentheticals first also stripped the brand names that live inside them, and
`BRAND_SYNONYMS` matches on exactly that text. "Butter (Chavroux brand)", the
example the original "Scoring corrections" section is built around, stopped
crediting goat cheese. It surfaced when I regenerated the whole August report
and "goat cheese" appeared as newly missed on photos 2 to 5; "Chavroux" appears
in 51 of the stored responses. The final version looks up brand names in
the unstripped text and matches everything else on the stripped text, with
tests for both. Figures in an earlier draft of this section (0.531, 0.507,
0.590) came from the intermediate scorer and are superseded by the ones below.

Near-miss audit across the 150 checkpointed responses (135 from August with
today's ministral-8b B-conservative calls replacing August's, plus 15 for
ministral-14b): **274 distinct near-miss pairs (513 occurrences) before the
fix, 119 (217) after.** What remains, none of it fixed:

- **Correct non-matches (the matcher is right).** `sugar substitute`,
  `sweetened condensed milk` and `milk substitute` are different products from
  `sugar` and `milk`; `cream cheese` is not `cheese` or `heavy cream`; `baby
  potatoes` is not `sweet potato`; `green leafy vegetables`, `green bottle` and
  `green onions` share only the word "green" with `green beans`; `tomato paste
  or sauce` is a processed product, not `tomato`.
- **Missing modifier vocabulary (a judgement call each; not added).** The
  head-noun containment rule exists, but these words are not in
  `COMPATIBLE_MODIFIERS`: `cherry tomatoes` -> `tomato` (11 occurrences),
  `chicken breast`/`chicken thighs` -> `chicken` (13), `sweet onion` -> `onion`
  (3), `semi-skimmed`/`half-fat milk` -> `milk`, `crystallized sugar` ->
  `sugar`, `ham slices` -> `ham`, `sweet corn` -> `corn`.
- **A genuinely missing synonym (not added).** `half and half cream` ->
  `heavy cream`, 19 occurrences. The existing entries match only the exact
  phrases `half and half` and `half half`.
- **Unparenthesized location tail (not fixed).** `<Onions in a container>`,
  `<Potatoes in a container>`, `<Strawberries in a container>`: three
  occurrences, all from the retired model under prompt A, so no effect on the
  chosen model.
- **Disjunctive answers.** `butter or margarine`, `milk or cream`: the model
  hedged between two items.

Effect on mean F1 over the same stored responses (original -> final scorer):

| model | prompt | before | after |
|---|---|---|---|
| mistral-medium-2505 | A-current | 0.313 | 0.594 |
| mistral-medium-2505 | B-conservative | 0.640 | 0.640 |
| mistral-medium-2505 | C-grounded | 0.588 | 0.588 |
| pixtral-12b-latest | A-current | 0.412 | 0.488 |
| pixtral-12b-latest | B-conservative | 0.429 | 0.538 |
| pixtral-12b-latest | C-grounded | 0.397 | 0.523 |
| ministral-8b-2512 (2026-08-22) | A-current | 0.352 | 0.457 |
| ministral-8b-2512 (2026-08-22) | B-conservative | 0.428 | 0.521 |
| ministral-8b-2512 (2026-08-22) | C-grounded | 0.440 | 0.515 |

The retired model's best configuration is unchanged because its pipe-delimited
output carries no parentheticals. Every other configuration rose, which is why
the gap between the retired model and its replacements is smaller than it
looked, though still real.

### 3. The parser defect: vision silently returned nothing on every photo

With the production prompt, `ministral-8b-2512` returns a well-formed JSON
object followed by a stray closing fence and no opening one:

````
  "total_items_found": 14,
  "photo_quality": "good, well-lit and clear",
  "notes": null
}
```
````

`json.loads` raised "Extra data", `analyze_fridge_photo` caught it and returned
an empty perception, and the recommendation carried on as if no photo had been
sent. **Parse success across the 30 test photos: 0 of 30 before the fix, 30 of
30 after** (fresh calls; the model still emits the trailing fence on all 30).

Why the vision path did not reuse `complete_json`'s fence handling: it had the
same logic. `providers/mistral.py` and `perception/processor.py` each carried
an identical regex that only matches when a fence is present at BOTH ends, and
the vision copy was a deliberate duplicate (a code comment records the choice
to copy a small private helper rather than import across the package
boundary). So `complete_json` had the same gap; it would have survived only
through its repair retry. The fix is one public `strip_code_fences` in
`providers/mistral.py` that removes a leading and a trailing fence
independently; the vision path now imports it and the duplicate is gone.

**Why a 100% failure rate was invisible, and what changed.** The log line was a
generic `vision_perception_provider_failed` warning that did not include the
response, and the function is built to degrade gracefully. That is right for an
occasional failure and wrong for a total one. Unparseable vision responses now
log `vision_response_unparseable` with the first 200 characters of the raw
response, and after 3 consecutive failures (any success resets the count) an
error-level `vision_parsing_failing_systematically` line. Tests cover the
fence variants, the 200-character head, the escalation and the reset.

Other degradation paths that could hide a systematic failure the same way
(found by searching for broad exception handlers; I read the perception,
search and reasoning ones, not every handler):

- **Text and voice extraction (`analyze_text_input`, `analyze_voice_memo`).**
  A failed extraction returns an empty result and the run continues, which
  silently drops dietary restrictions and avoid lists. This is the most
  serious one, because it turns a systematic extraction failure into
  recommendations that ignore a stated allergy. It logs a warning with no
  escalation and no raw response.
- **`search_recipes`.** Any exception, or a failed MCP tool call, becomes an
  empty result with `search_exhausted=True`, which the pipeline presents as an
  honest "nothing matched". A total search outage is indistinguishable from a
  genuinely unsatisfiable request, and Dimension 2 treats honest refusal as a
  pass, so such an outage would currently pass its unsatisfiable cases.
- **`reason`.** Any exception, or a recipe id the model was not offered, falls
  back to the top-ranked candidate with a flag (`invalid_model_choice`) and a
  warning. A systematically failing reasoning model would produce plausible
  recommendations with no reasoning behind them.
- **`generate_output` and `match_rank`.** Substitutions, grocery list and
  nutrition each have their own catch-and-continue; a systematic failure drops
  that part of the output without anything failing.
- **Context signals (weather, time).** A missing API key or failed lookup
  returns nothing and the signal is simply omitted.
- **Provider rate-limit exhaustion.** After the retries, a 429 becomes the same
  empty-perception result as a parse failure, so an exhausted quota looks like
  "no photo".

A shared remedy would be a small consecutive-failure counter like the one now
in the vision path, applied to each of these. Not done here.

### 4. Re-measurement with vision working

B-conservative, photo_01 to photo_05, 3 reps, temperature 0, corrected parser
and corrected scorer, fresh calls on 2026-10-16, two ways.

**(a) Benchmark methodology** (the script's own pipe-format prompt, the method
behind the retired model's 0.64, so directly comparable to it):

| model | F1 before fix | F1 after fix | stddev | adj. F1 | precision | recall (raw) |
|---|---|---|---|---|---|---|
| mistral-medium-2505 (retired, 2026-08-22) | 0.640 | 0.640 | 0.077 | 0.651 | 0.707 | 0.586 |
| mistral-medium-2604 | not measurable (0 req/min) | | | | | |
| ministral-14b-2512 | 0.400 | 0.551 | 0.097 | 0.562 | 0.618 | 0.498 |
| ministral-8b-2512 | 0.490 | 0.545 | 0.075 | 0.550 | 0.579 | 0.516 |

**(b) Production path** (`analyze_fridge_photo` end to end: the production JSON
prompt, the fixed parser; "model names" scores what the model wrote, "after
canonicalization" scores what the pantry would actually receive):

| model | parsed | F1, model names | stddev | F1, after canonicalization | precision | recall (raw) |
|---|---|---|---|---|---|---|
| ministral-14b-2512 | 15/15 | 0.535 | 0.053 | 0.504 | 0.616 | 0.473 |
| ministral-8b-2512 | 15/15 | 0.529 | 0.103 | 0.489 | 0.582 | 0.486 |

Per-photo stddev is below 0.10 for every cell of both models and both methods.
The 0.103 for 8b in (b) is the spread across all 15 calls, mostly between
photos (photo_02 and photo_04 score about 0.42 and photo_05 0.64), not
instability within a photo.

**The tie holds.** 0.551 vs 0.545 (benchmark) and 0.535 vs 0.529 (production)
are 0.006 apart, an order of magnitude smaller than the roughly 0.06 drift
seen when ministral-8b was re-run against its own August results.

Canonicalization costs both models about 0.03 to 0.04 F1, and the cause is a
real pipeline behaviour rather than a scoring one: `normalize_ingredient`
deletes the parentheses but keeps the words inside them, so the qualifier
becomes part of the stored name. From one stored photo_01 run: "sugar packets
(beaten sugar)" is stored as `sugar sugar`, "yogurt drink (blue carton)" as
`yogurt drink blue`, "sauce or jam (small orange jar)" as `sauce or jam
orange`, and "packaged meat (looks like ham or pork)" as `meat look like ham or
pork`. Those names then fail to match recipe ingredients as cleanly as the
bare noun would. Not changed here; worth its own look.

### 5. Choice and throughput

F1 does not separate the two, so the decision is throughput, and the headline
TPM numbers point the other way from the binding limit. A recommendation that
includes a photo makes about 3 LLM calls and about 6,000 to 7,000 tokens.

- **ministral-8b-2512:** 625,000 TPM allows about 90 such recommendations a
  minute; 3.13 RPS allows about 187 calls a minute. With three calls per
  recommendation the request limit binds at roughly 60 recommendations a
  minute.
- **ministral-14b-2512:** 937,500 TPM would allow about 135 a minute, but
  0.50 RPS is 30 calls a minute. Even with only vision and reasoning on it (two
  calls) that is about 15 recommendations a minute, and it would make a 30-case
  evaluation run several times slower.

The effective ceiling is requests, not tokens, so **ministral-8b-2512 is the
better choice** and `VISION_MODEL` and `REASONING_MODEL` stay as they are.
14b's lower aggregate spread in the production path (0.053 against 0.103) is a
point in its favour, and it has the token headroom if the request limit is ever
raised. 14b has no entry in
`MODEL_RATE_LIMITS` today, so using it would need one (937,500 TPM, 0.50 RPS).
The choice costs roughly 0.10 F1 against the retired model's 0.640 (0.545 on the same methodology).

### 6. Audit of claims that depended on the old scorer

| claim | where | status |
|---|---|---|
| Prompt A "fails catastrophically at 0.00 F1" on photo_03/04; B succeeds | VISION_FINDINGS.md; benchmark report; `perception/prompt.py` docstring; `notes/phase_5_1_*.txt` | **Invalid.** Scoring artifact; A is 0.594 vs B 0.640. Corrected inline in both docs and the docstring; the phase note is a dated historical record and was left unedited. |
| Mechanism: "the pipe delimiter protects the item name" | VISION_FINDINGS.md | **Not supported** (nothing catastrophic to explain). |
| "Prompt A's failure is tied to the ABSENCE of the 'cannot identify' permission" | `perception/prompt.py` docstring, phase 5.1 note | **Not supported.** Neither the original explanation nor the 0.00 survives; docstring corrected. The permission is kept as a sensible default only. |
| Ranking of the 9 (model, prompt) pairs; per-model and per-prompt aggregates | benchmark report | **Changed.** The best configuration is the same, but medium-2505 + A moves from last (9th) to 2nd; the A-vs-B aggregate gap goes from 0.14 to 0.06; model aggregates become 0.61 / 0.52 / 0.50 (medium / pixtral / ministral-8b) from 0.51 / 0.41 / 0.41. |
| Per-image mean F1 (0.44, 0.46, 0.43, 0.36, 0.54) | benchmark report | **Changed** to 0.51, 0.53, 0.57, 0.48, 0.61. |
| "Items every model reported that are never in ground truth", including `<Potatoes in a container>` | benchmark report | **Wrong in part.** That entry is potatoes; the scorer failed on its location tail. The corrected list has 9 entries, none of them that one. |
| Best configuration = medium-2505 + B, F1 0.64 | everywhere | **Holds** (unchanged). |
| Visibility adjustment lifts photo_01 recall 0.62 -> 0.69 | VISION_FINDINGS.md | **Holds** (best configuration unaffected). |
| "Dataset ceiling about 0.77 to 0.79"; shrimp and spinach never identified | VISION_FINDINGS.md | **Holds** (best per-image F1 now 0.67, 0.67, 0.79, 0.71, 0.79). |
| Resolution sensitivity 0.67 -> 0.52 -> 0.43 | VISION_FINDINGS.md | **Partially holds**, see the note on that section: direction yes, figures and monotonic shape no. Also quoted in a `settings.py` comment, now corrected. |
| mistral-small-2603 scored 0.07 | VISION_FINDINGS.md | **Not re-measurable** (model unreachable). It comes from the diagnostic script's own scorer, a separate code path from this defect; unverified rather than known-good. |
| Scoring corrections: medium-2505 + B 0.55 -> 0.64 | benchmark report | **Holds.** |

The original tables in the benchmark report were not edited; its addendum has
the regenerated ones.

### 7. Reasoning faithfulness (10 real recommendations, measured, prompt untouched)

Ten full runs through `run_recommendation` with a photo and a natural-language
request each, on 2026-10-16, with vision working (12 to 18 items per photo).
Schema validation held: all `RecipeDecision` outputs valid, no repair retry, no
fallback. Two requests ("something Italian", "a vegan dinner") returned no
recommendation because nothing was cookable; those explanations are
templated, not model text, so 8 runs have reasoning to check. Each claim was
checked against the chosen recipe's actual ingredient list and against the
exact prompt sent (captured from the call).

**6 of 10 runs state that the recipe uses an ingredient it does not contain**
(6 of the 8 with model reasoning):

| run | request | recipe | false claim |
|---|---|---|---|
| 1 | quick dinner for 2 | Pierogi | "uses an ingredient that is about to expire (meat possibly ham or pork)"; no ham or pork in the recipe |
| 4 | anything with chicken, for 4 | Kumpir | "uses available ingredients like potato ... and demi cr me milk (potentially a substitute for yogurt or cream)"; no milk, yogurt or cream in the recipe |
| 5 | use up what is expiring | Kumpir | "uses chicken and sweet potato, both expiring soon"; no chicken in the recipe |
| 8 | light, under 20 minutes | Pierogi | "uses chicken breast, which is expiring soon (49 days left)"; no chicken, and the data says -49 days (already past) |
| 9 | comfort food for 3 | Kumpir | "The recipe uses ham, which is listed as expiring in 2 days"; no ham in the recipe |
| 10 | seafood or fish if possible | Kumpir | "uses available ingredients like tomato, onion, and potato"; no tomato in the recipe |

Every one of the six named an item from the supplied "Available ingredients"
list (five of the six also from "Expiring soon"), so these are not random
inventions: the model attributes pantry items to a recipe that does not use
them. The prompt tells it only that a recipe "uses an ingredient that's about
to expire", without naming which, and does not list the recipe's matched
ingredients; this is the likely cause, but I have not tested it.

Other unsupported claims, same runs and the rest:

- **Run 7 (Chicken Enchilada Casserole):** ingredient claims are correct, but
  it says the 45-minute cook time "is within the 30-minute max constraint if
  optimized" (45 > 30; the search relaxed the ceiling and the model was not
  told), and says "the cuisine preference is Mexican instead of Indian" when
  the user asked for Indian and Mexican is a stored profile weight.
- **Run 10:** claims "the protein preference is met" for a recipe with no
  seafood or fish, which was the request.
- **Run 3 (borderline, not counted):** "the recipe uses sweet potato"; the
  recipe lists plain potatoes and the pipeline's own matcher counted a sweet
  potato as satisfying them.
- **Numbers:** every figure the model cited is in the prompt or is a simple
  per-serving division of one; none was invented.

Counting any unsupported factual claim at all, 7 of the 10 runs have at least
one (runs 1, 4, 5, 7, 8, 9, 10), plus the borderline run 3. Note this check
used one fixed set of 10 requests and one model at temperature 0, so it
measures this configuration, not a distribution.

A separate defect surfaced in run 4: the request "Anything with chicken, for 4
people" was extracted as `avoid ingredients: chicken`. That is the opposite of
the request, from the text-extraction step (also ministral-8b-2512), and the
recommendation then correctly "avoided chicken". It is outside this task and
untouched.
