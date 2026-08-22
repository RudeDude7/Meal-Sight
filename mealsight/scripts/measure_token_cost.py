#!/usr/bin/env python3
"""Estimate real-world token cost of a single MealSight reasoning call.

Builds a worst-case-realistic prompt (full pantry, recipe corpus, meal
history, preference profile), sends it to Mistral, and reports token usage
plus a theoretical throughput ceiling for the pipeline.

Run with: uv run --with httpx scripts/measure_token_cost.py
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
REQUEST_TIMEOUT = 30
MODEL = "mistral-medium-2505"

CALLS_PER_RECOMMENDATION = 6
TPM_CEILING = 1_000_000
MODEL_RPS_LIMIT = 5  # per-model requests-per-second cap on the standard tier


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def build_pantry() -> list[dict[str, str]]:
    return [
        {"item": "chicken thighs", "quantity": "1.2 lb", "freshness": "use within 2 days"},
        {"item": "red bell pepper", "quantity": "2", "freshness": "fresh, 5 days left"},
        {"item": "whole milk", "quantity": "0.5 gal", "freshness": "use within 4 days"},
        {"item": "brown rice", "quantity": "3 cups dry", "freshness": "pantry stable"},
        {"item": "spinach", "quantity": "5 oz bag", "freshness": "wilting, use today"},
        {"item": "cheddar cheese", "quantity": "8 oz block", "freshness": "fresh, 2 weeks left"},
        {"item": "eggs", "quantity": "9 count", "freshness": "fresh, 10 days left"},
        {"item": "yellow onion", "quantity": "3", "freshness": "pantry stable"},
        {"item": "canned black beans", "quantity": "2 cans", "freshness": "pantry stable"},
        {"item": "garlic", "quantity": "1 bulb", "freshness": "pantry stable"},
    ]


def build_recipes() -> list[dict[str, Any]]:
    templates = [
        ("Chicken Stir Fry", ["chicken thighs", "bell pepper", "soy sauce", "rice", "garlic"]),
        ("Spinach Egg Scramble", ["eggs", "spinach", "cheddar cheese", "butter"]),
        ("Black Bean Rice Bowl", ["black beans", "brown rice", "onion", "lime", "cilantro"]),
        ("Cheesy Chicken Bake", ["chicken thighs", "cheddar cheese", "milk", "breadcrumbs"]),
        ("Garlic Rice Pilaf", ["brown rice", "garlic", "onion", "chicken broth"]),
        ("Veggie Frittata", ["eggs", "bell pepper", "spinach", "onion", "milk"]),
        ("Onion Bean Soup", ["black beans", "onion", "garlic", "vegetable broth"]),
        ("Pepper Chicken Skillet", ["chicken thighs", "bell pepper", "onion", "paprika"]),
        ("Cheese and Rice Casserole", ["brown rice", "cheddar cheese", "milk", "eggs"]),
        ("Garlic Spinach Saute", ["spinach", "garlic", "olive oil", "lemon"]),
    ]
    return [
        {"name": name, "ingredients": ingredients, "prep_minutes": 25}
        for name, ingredients in templates
    ]


def build_meal_history() -> list[dict[str, str]]:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    meals = [
        "Grilled salmon with asparagus",
        "Turkey chili",
        "Vegetable stir fry with tofu",
        "Beef tacos",
        "Margherita pizza",
        "Shrimp pasta",
        "Roast chicken with potatoes",
    ]
    return [{"day": day, "meal": meal} for day, meal in zip(days, meals)]


def build_preference_profile() -> dict[str, Any]:
    return {
        "dietary_restrictions": ["no shellfish allergy accommodation needed", "prefers low-sodium"],
        "cuisine_preferences": ["Mediterranean", "Mexican", "American comfort food"],
        "disliked_ingredients": ["cilantro", "blue cheese"],
        "cooking_skill": "intermediate",
        "max_prep_minutes": 40,
        "household_size": 3,
        "goal": "high-protein, moderate-carb dinners this week",
    }


def build_prompt() -> str:
    payload = {
        "pantry": build_pantry(),
        "available_recipes": build_recipes(),
        "meal_history_last_7_days": build_meal_history(),
        "user_preference_profile": build_preference_profile(),
    }
    instructions = (
        "You are MealSight's meal recommendation reasoning engine. Given the "
        "pantry inventory, candidate recipes, the last 7 days of meals eaten, "
        "and the user's preference profile below, recommend the single best "
        "dinner for tonight. Explain your reasoning in 3-5 sentences, "
        "referencing pantry freshness, variety versus recent meal history, "
        "and preference fit. Then output a structured JSON object with keys "
        "'recommended_recipe', 'reasoning', and 'pantry_items_used'.\n\n"
        f"DATA:\n{json.dumps(payload, indent=2)}"
    )
    return instructions


def http_post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, bytes]:
    data = json.dumps(body).encode("utf-8")
    req_headers = dict(headers)
    req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def call_mistral(api_key: str, prompt: str) -> dict[str, Any]:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    status, response_body = http_post_json(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        body=body,
    )
    if status != 200:
        raise RuntimeError(f"Mistral API returned HTTP {status}: {response_body[:300]!r}")
    payload = json.loads(response_body)
    return payload


def print_report(usage: dict[str, int]) -> None:
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

    estimated_recommendation_tokens = total_tokens * CALLS_PER_RECOMMENDATION

    calls_per_second_by_tpm = TPM_CEILING / 60 / max(total_tokens, 1)
    effective_calls_per_second = min(calls_per_second_by_tpm, MODEL_RPS_LIMIT)
    recommendations_per_hour = (effective_calls_per_second * 3600) / CALLS_PER_RECOMMENDATION

    print("\n" + "=" * 60)
    print("TOKEN BUDGET REPORT")
    print("=" * 60)
    print(f"Model: {MODEL}")
    print(f"Single call — input tokens:  {input_tokens}")
    print(f"Single call — output tokens: {output_tokens}")
    print(f"Single call — total tokens:  {total_tokens}")
    print()
    print(f"Estimated tokens for a full recommendation ({CALLS_PER_RECOMMENDATION} calls): "
          f"{estimated_recommendation_tokens}")
    print()
    print(f"TPM ceiling: {TPM_CEILING:,} tokens/min")
    print(f"Per-model RPS limit: {MODEL_RPS_LIMIT} req/s")
    print(f"Calls/sec bound by TPM: {calls_per_second_by_tpm:.2f}")
    print(f"Calls/sec bound by RPS limit: {MODEL_RPS_LIMIT}")
    print(f"Effective calls/sec (binding constraint): {effective_calls_per_second:.2f}")
    print()
    print(f"Theoretical recommendations/hour ceiling: {recommendations_per_hour:.1f}")
    print("=" * 60)


def main() -> int:
    env = load_env(ENV_PATH)
    api_key = env.get("MISTRAL_API_KEY")
    if not api_key:
        logger.error("MISTRAL_API_KEY not set in .env — cannot measure token cost")
        return 1

    prompt = build_prompt()
    logger.info("Prompt built (%d characters). Sending to %s...", len(prompt), MODEL)

    try:
        payload = call_mistral(api_key, prompt)
    except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
        logger.error("Mistral call failed: %s", exc)
        return 1

    usage = payload.get("usage", {})
    if not usage:
        logger.error("Response contained no usage data: %s", json.dumps(payload)[:300])
        return 1

    print_report(usage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
