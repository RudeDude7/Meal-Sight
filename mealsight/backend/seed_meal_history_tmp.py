"""Adds realistic demo meal history via the real log_meal function
(not raw SQL) against the real user_intelligence.db, for a meaningful
get_taste_insights verification demonstration. Backed up beforehand;
restored after verification. Every recipe_id/name/cuisine below is a
REAL row from the real recipes.db, confirmed directly before writing
this script."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from mealsight.user_intelligence.meal_history import log_meal


async def main() -> None:
    today = date.today()

    # Italian, chicken-skewed (4 of 6 meals use chicken) — real recipes,
    # real cuisine field values, confirmed against recipes.db directly.
    italian_meals = [
        ("52780", "Potato Gratin with Chicken", 4, 1),
        ("52796", "Chicken Alfredo Primavera", 5, 3),
        ("52780", "Potato Gratin with Chicken", 4, 6),
        ("52796", "Chicken Alfredo Primavera", 3, 9),
        ("52770", "Spaghetti Bolognese", 3, 12),
        ("52810", "Osso Buco alla Milanese", 5, 15),
    ]
    for recipe_id, name, rating, days_ago in italian_meals:
        await log_meal(recipe_id, name, "Italian", "dinner", today - timedelta(days=days_ago), rating=rating)

    # Mexican, rated highly, not cooked in over 3 weeks.
    await log_meal(
        "52826", "Braised Beef Chilli", "Mexican", "dinner", today - timedelta(days=25), rating=5
    )

    print("Seeded 7 real, demo meal_history rows via the real log_meal function.")


if __name__ == "__main__":
    asyncio.run(main())
