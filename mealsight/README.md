# MealSight

[![CI](https://github.com/RudeDude7/Meal-Sight/actions/workflows/ci.yml/badge.svg)](https://github.com/RudeDude7/Meal-Sight/actions/workflows/ci.yml)
[![Eval regression gate](https://github.com/RudeDude7/Meal-Sight/actions/workflows/eval-nightly.yml/badge.svg)](https://github.com/RudeDude7/Meal-Sight/actions/workflows/eval-nightly.yml)

MealSight is a multimodal agentic meal recommendation system: it reasons over photos of your pantry, spoken input, and meal history to suggest what to cook next. It combines vision, speech, and language models with real-world recipe and weather data to keep recommendations grounded and current.

Status: pre-development setup

## Operating characteristics (free tier)

Mistral cut the free tier mid-project: `ministral-8b-2512` is now **2 requests/minute and 40,000 tokens/minute**, measured from live rate-limit headers on 2026-11-07 (it was 3.13 requests/s and 625,000 tokens/min when the project began). Limits like these have changed once already, so re-verify them (`python -m eval.preflight` prints the headers) instead of trusting any number written here.

The limiter now paces calls to what the provider allows, so a recommendation is slow on this tier. Measured end to end:

| Input | Provider calls | Wall-clock | Of which rate-limit waiting |
|---|---|---|---|
| text only | 2 | 32.6 s | 28.7 s (API time 3.4 s) |
| photo + text | 3 | 61.8 s (64.3 s in the latest WebSocket trace) | 58.5 s (API time 7.8 s) |

Phase 8 measured 11.3 s before the tier change. The product is usable as a demo at about a minute per photo recommendation, not as an interactive tool; the cost is waiting, not API time. A paid tier with higher limits removes the wait. Both stages that call the provider (perception and reasoning) send a progress line every 2.5 s. While a call is queued behind the rate limiter the line says so with a countdown ("Waiting for the rate limit, not computing: the free tier allows 2 requests a minute... About 21s to go"), so a 60-second run never goes silent for more than 2.5 s.

## Setup

1. Copy `.env.example` to `.env` and fill in `MISTRAL_API_KEY`, `GROQ_API_KEY`, and `OPENWEATHER_API_KEY`.
2. Verify local tooling:
   ```
   python3 scripts/check_environment.py
   ```
3. Verify external API access (drop a photo in `test_data/images/` and an audio clip in `test_data/audio/` first to exercise the vision and transcription checks):
   ```
   uv run --with httpx scripts/smoke_test.py
   ```
4. Measure token cost for a realistic reasoning call:
   ```
   uv run --with httpx scripts/measure_token_cost.py
   ```

This README will be rewritten once application development starts.
