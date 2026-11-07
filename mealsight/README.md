# MealSight

[![CI](https://github.com/RudeDude7/Meal-Sight/actions/workflows/ci.yml/badge.svg)](https://github.com/RudeDude7/Meal-Sight/actions/workflows/ci.yml)
[![Eval regression gate](https://github.com/RudeDude7/Meal-Sight/actions/workflows/eval-nightly.yml/badge.svg)](https://github.com/RudeDude7/Meal-Sight/actions/workflows/eval-nightly.yml)

MealSight is a multimodal agentic meal recommendation system: it reasons over photos of your pantry, spoken input, and meal history to suggest what to cook next. It combines vision, speech, and language models with real-world recipe and weather data to keep recommendations grounded and current.

Status: pre-development setup

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
