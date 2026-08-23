#!/usr/bin/env python3
"""Fetches recipes from TheMealDB and loads them into recipes.db.

Fetch strategy: enumerate every category and every area, use filter.php to
collect meal ids from each, deduplicate, then call lookup.php once per id
for full detail. Every raw HTTP response is cached to a gitignored
backend/.cache/ directory keyed by request URL, so re-running this script
never re-fetches anything it already has on disk — the network is only
ever hit for genuinely new requests.

Loading is idempotent: recipes are written with INSERT OR REPLACE keyed on
TheMealDB's own id (recipes.id is TEXT PRIMARY KEY), so running this
script twice re-derives and overwrites the same rows rather than
duplicating them.

cook_time_source: TheMealDB has no cook-time field, so this script
estimates one (see recipe_parsing.estimate_cook_time_minutes) and records
how it was derived. The task authorized either adding a new column via
ALTER TABLE or folding it into existing JSON; this script adds a column
(recipes.cook_time_source, TEXT, added idempotently if not already
present) rather than repurposing dietary_tags/ingredients/steps, since
each of those already has a documented shape other code depends on, and
none of them has room for a per-recipe metadata field without breaking
that documented shape.

Run with (from backend/):
    uv run python -m mealsight.seed.recipes_from_mealdb
or as part of the full pipeline:
    uv run mealsight-seed
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from mealsight.config.settings import settings
from mealsight.db import Database, get_recipe_db
from mealsight.providers.retry import request_with_retry
from mealsight.utils.logging import get_logger

from .recipe_parsing import (
    assign_importances,
    derive_dietary_tags,
    estimate_cook_time_minutes,
    map_area_to_cuisine,
    map_category_to_meal_type,
    parse_measure,
    split_steps,
)

logger = get_logger("mealsight.seed.recipes_from_mealdb")

# mealsight/seed/recipes_from_mealdb.py -> mealsight/seed -> mealsight -> backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = BACKEND_DIR / ".cache" / "themealdb"

THROTTLE_SECONDS = 0.35
MAX_RECIPES = 250
INGREDIENT_SLOTS = 20


def _cache_path_for(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


async def fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """GETs a TheMealDB URL, serving from the on-disk cache when present,
    otherwise fetching (with retry on transient failure) and caching the
    parsed JSON body for next time."""
    cache_path = _cache_path_for(url)
    if cache_path.exists():
        payload: dict[str, Any] = json.loads(cache_path.read_text())
        return payload

    await asyncio.sleep(THROTTLE_SECONDS)

    async def make_request() -> httpx.Response:
        return await client.get(url)

    response = await request_with_retry(make_request, provider="themealdb", model_id="n/a", logger=logger)
    response.raise_for_status()
    payload = response.json()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload))
    return dict(payload)


async def fetch_categories(client: httpx.AsyncClient) -> list[str]:
    url = f"{settings.themealdb_base_url}/categories.php"
    payload = await fetch_json(client, url)
    return [c["strCategory"] for c in payload.get("categories", []) if c.get("strCategory")]


async def fetch_areas(client: httpx.AsyncClient) -> list[str]:
    url = f"{settings.themealdb_base_url}/list.php?a=list"
    payload = await fetch_json(client, url)
    return [a["strArea"] for a in payload.get("meals", []) or [] if a.get("strArea")]


async def fetch_meal_ids_for_filter(client: httpx.AsyncClient, param: str, value: str) -> list[str]:
    url = f"{settings.themealdb_base_url}/filter.php?{param}={value}"
    payload = await fetch_json(client, url)
    meals = payload.get("meals") or []
    return [m["idMeal"] for m in meals if m.get("idMeal")]


async def fetch_meal_detail(client: httpx.AsyncClient, meal_id: str) -> dict[str, Any] | None:
    url = f"{settings.themealdb_base_url}/lookup.php?i={meal_id}"
    payload = await fetch_json(client, url)
    meals = payload.get("meals") or []
    return meals[0] if meals else None


async def collect_meal_ids(client: httpx.AsyncClient) -> list[str]:
    categories = await fetch_categories(client)
    areas = await fetch_areas(client)
    logger.info("discovered_categories_and_areas", categories=len(categories), areas=len(areas))

    meal_ids: set[str] = set()
    for category in categories:
        ids = await fetch_meal_ids_for_filter(client, "c", category)
        meal_ids.update(ids)
    for area in areas:
        ids = await fetch_meal_ids_for_filter(client, "a", area)
        meal_ids.update(ids)

    ordered = sorted(meal_ids, key=int)
    logger.info("collected_meal_ids", total=len(ordered))
    return ordered[:MAX_RECIPES]


def _extract_raw_ingredients(meal: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for slot in range(1, INGREDIENT_SLOTS + 1):
        name = (meal.get(f"strIngredient{slot}") or "").strip()
        measure = (meal.get(f"strMeasure{slot}") or "").strip()
        if name:
            pairs.append((name, measure))
    return pairs


def build_recipe_row(meal: dict[str, Any]) -> dict[str, Any]:
    """Transforms one TheMealDB lookup.php meal record into a
    recipes.db row, applying every required transformation."""
    name = meal["strMeal"]
    raw_ingredients = _extract_raw_ingredients(meal)
    ingredient_names = [name for name, _measure in raw_ingredients]
    importances = assign_importances(name, ingredient_names)

    ingredients = []
    for (ingredient_name, raw_measure), importance in zip(raw_ingredients, importances, strict=True):
        quantity, unit = parse_measure(raw_measure)
        ingredients.append(
            {
                "name": ingredient_name,
                "quantity": quantity,
                "unit": unit,
                "importance": importance,
                "raw_measure": raw_measure,
            }
        )

    instructions = meal.get("strInstructions") or ""
    steps = split_steps(instructions)
    cook_time_minutes, cook_time_source = estimate_cook_time_minutes(instructions, len(steps))
    dietary_tags = derive_dietary_tags(ingredient_names)
    cuisine = map_area_to_cuisine(meal.get("strArea"), meal.get("strCountry"))
    meal_type = map_category_to_meal_type(meal.get("strCategory"))

    return {
        "id": meal["idMeal"],
        "name": name,
        "cuisine": cuisine,
        "meal_type": meal_type,
        "cook_time_minutes": cook_time_minutes,
        "cook_time_source": cook_time_source,
        "prep_time_minutes": None,
        "difficulty": None,
        "servings_base": 4,
        "dietary_tags": json.dumps(dietary_tags),
        "ingredients": json.dumps(ingredients),
        "steps": json.dumps(steps),
        "image_url": meal.get("strMealThumb"),
        "source": meal.get("strSource"),
    }


async def ensure_cook_time_source_column(db: Database) -> None:
    """Adds recipes.cook_time_source if it isn't already there. Checked
    every run (idempotent) since SQLite's ALTER TABLE ADD COLUMN has no
    IF NOT EXISTS clause of its own."""
    columns = await db.fetch_all("PRAGMA table_info(recipes)")
    column_names = {row["name"] for row in columns}
    if "cook_time_source" not in column_names:
        await db.execute("ALTER TABLE recipes ADD COLUMN cook_time_source TEXT")
        logger.info("added_column", table="recipes", column="cook_time_source")


async def upsert_recipe(db: Database, row: dict[str, Any]) -> None:
    await db.execute(
        """
        INSERT OR REPLACE INTO recipes (
            id, name, cuisine, meal_type, cook_time_minutes, cook_time_source,
            prep_time_minutes, difficulty, servings_base, dietary_tags,
            ingredients, steps, image_url, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"], row["name"], row["cuisine"], row["meal_type"],
            row["cook_time_minutes"], row["cook_time_source"], row["prep_time_minutes"],
            row["difficulty"], row["servings_base"], row["dietary_tags"],
            row["ingredients"], row["steps"], row["image_url"], row["source"],
        ),
    )


async def run(db: Database | None = None) -> int:
    """Fetches and loads recipes. Returns the number of recipes loaded."""
    owns_db = db is None
    db = db or get_recipe_db()
    await ensure_cook_time_source_column(db)

    loaded = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        meal_ids = await collect_meal_ids(client)
        for meal_id in meal_ids:
            meal = await fetch_meal_detail(client, meal_id)
            if meal is None:
                continue
            row = build_recipe_row(meal)
            await upsert_recipe(db, row)
            loaded += 1

    logger.info("recipes_loaded", count=loaded)
    if owns_db:
        await db.close()
    return loaded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    count = asyncio.run(run())
    print(f"Loaded {count} recipes into {settings.recipes_db_path}")
