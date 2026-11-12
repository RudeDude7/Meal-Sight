# Known Issues

Deferred findings from prior verification passes. Each entry below was deliberately not fixed
at the time it was found — recorded here instead of silently left implicit, so the reason it
was deferred and what a real fix would involve isn't lost.

## 1. `derive_dietary_tags`'s `EGG_TERMS` check uses raw substring matching

**Where:** `backend/mealsight/seed/recipe_parsing.py`, `_any_term_matches` / `EGG_TERMS`.

**Description:** Dietary tag derivation checks whether any ingredient name contains an
`EGG_TERMS` entry (`egg`, `eggs`, `egg yolk`, `egg white`, `mayonnaise`, `meringue`) using plain
substring containment (`term in name`), not whole-word matching. `"egg"` is a substring of
`"eggplant"`, so a recipe whose only "egg-like" ingredient is eggplant would incorrectly have
its `vegan`/`egg_free`-adjacent classification affected as if it contained real eggs.

**Currently masked because:** the seeded recipe corpus (sourced from TheMealDB, which leans
British/international) consistently uses "aubergine" rather than "eggplant" for this vegetable,
so the collision has not yet produced a wrong tag on any real recipe in the current 250-recipe
corpus. It is a live bug, just not yet triggered by the data on hand.

**Why deferred:** found during the Phase 2.2 importance-heuristic investigation, which was
explicitly scoped to `assign_importances`, not `derive_dietary_tags`. The same substring-vs-
whole-word bug pattern was fixed in `assign_importances` in that session (see
`_matches_any_term_whole_word` and its docstring, which documents the near-identical
`"reggiano"` contains `"egg"` bug it replaced) — fixing `derive_dietary_tags` too would have
been a reasonable, low-risk extension of that same fix, but doing it unprompted, outside the
task's stated scope, was judged more likely to cause confusion than help, especially since it
would trigger a re-seed and a fresh dietary-tag audit of the whole corpus.

**What a fix would involve:** replace the substring check in `_any_term_matches` (used by
`derive_dietary_tags` for `MEAT_TERMS`, `DAIRY_TERMS`, `EGG_TERMS`, `HONEY_TERMS`, and
`NUT_TERMS` alike) with the same `\b`-word-boundary regex approach already used in
`_matches_any_term_whole_word` for importance assignment. This should be done for all five term
lists at once, not just `EGG_TERMS`, since the same collision risk exists wherever any of those
lists' entries could be a substring of an unrelated ingredient name (worth a fresh scan for
other collisions, not just eggplant/egg, before shipping). It requires a full re-run of
`mealsight-seed` afterward and a fresh dietary-tag safety audit (the same kind of check
`scripts/audit_recipe_data.py` already runs) to confirm nothing regressed.

## 2. Non-protein defining ingredients never reach `critical` importance

**Where:** `backend/mealsight/seed/recipe_parsing.py`, `assign_importances`.

**Description:** An ingredient can only become `critical` two ways: its normalized name is a
literal substring of the recipe's own title, or (if nothing matches the title) it's the first
ingredient matching a `PROTEIN_TERMS` entry. Ingredients that define a dish without being a
protein and without appearing in the recipe's title text never become `critical` — they default
to `important`, indistinguishable from any other supporting ingredient in the recipe. Example:
potato is the defining ingredient of a Spanish tortilla (tortilla española = potato omelette),
but "potato" appears nowhere in the English title "Spanish Tortilla," and potato isn't a
`PROTEIN_TERMS` entry — so it's classified `important`, not `critical`, and a matcher run
missing only potato scores the same as if it were missing any other supporting vegetable.

**Why deferred:** found during the same Phase 2.2 importance-heuristic investigation, which
explicitly asked not to over-engineer a fix without a clear pattern. Fixing this well requires
a genuinely subjective judgment call — which non-protein ingredients are "defining" enough to
deserve `critical` (potato for a tortilla, arguably rice for a fried rice, pasta shape for a
pasta dish) is a fuzzier line than the mechanical substring-matching bug in issue #1 above, and
a poorly-scoped staple-ingredient list risks scope creep or overcorrecting toward marking too
many things critical. Two other sampled recipes in the same review (Fettucine alfredo, Baingan
Bharta) hit the same gap from the opposite direction — no ingredient matched either rule at all,
so no ingredient became critical for those recipes, rather than the wrong one being picked.

**What a fix would involve:** a real design decision, not a mechanical patch — likely a curated
list of non-protein "defining staple" terms (starches central to a dish's identity: potato,
rice, pasta shape names, bread) analogous to `PROTEIN_TERMS`, checked as a second fallback tier
after the title-match and protein-match checks both fail. That list would need its own
deliberate scoping (which staples count, and for which dishes) and its own test coverage before
being trusted — exactly the kind of judgment call this task's "don't over-engineer" instruction
was aimed at avoiding without first confirming the error rate justifies it.

## 3. WebSocket subscriptions are not origin-checked

**Where:** `backend/mealsight/api/routers/ws.py` (`/ws/{session_id}`) and the CORS setup in `backend/mealsight/api/app.py`.

**Description:** `CORS_ALLOWED_ORIGINS` is enforced by Starlette's `CORSMiddleware`, which only applies to HTTP
requests. Browsers do not apply CORS to WebSocket upgrades at all, and the backend does not look at the `Origin`
header of the upgrade request. So the allow-list protects the REST endpoints but not the WebSocket: a page served from
any origin can open `/ws/{session_id}` and subscribe, provided it knows the session id. (Verified against the
deployed file set: a cross-origin upgrade with an allowed `Origin` succeeds, and nothing in the code would reject a
disallowed one.)

**Why it is not exploitable in practice:** a session id is a random UUID (version 4, from `uuid.uuid4()`), returned only
to the client that started the run, so it cannot be guessed or enumerated, and a session only carries that one run's
progress messages and result. There is also no authentication or per-user data in this single-user demo for the
socket to expose beyond that. It is an inconsistency in the protection, not a known leak.

**Why deferred:** low risk for a single-user demo, and the check is easy to get subtly wrong: an exact-match allow-list
would reject non-browser clients that send no `Origin` and any preview deployment not on the list.

**What a fix would involve:** read `websocket.headers.get("origin")` in the WebSocket handler before `accept()` and close
with code 1008 (policy violation) when it is present and not in `settings.cors_allowed_origins`, reusing the same list
so REST and WebSocket cannot drift apart. Decide explicitly what to do with a missing `Origin` (non-browser clients,
tests) and add tests for an allowed origin, a disallowed origin and an absent one. If sessions ever carry user data,
also bind the session id to the requesting client (for example a short-lived token returned by `POST /api/recommend`
and required on the upgrade), since the Origin header is not a credential.
