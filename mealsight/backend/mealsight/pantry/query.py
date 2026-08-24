"""get_pantry — reads back what's currently believed to be in the
pantry, with days_remaining computed per item.

Deterministic, no LLM calls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mealsight.config.settings import settings
from mealsight.db import get_pantry_db
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.pantry._datetime_utils import parse_sqlite_timestamp
from mealsight.pantry.models import FreshnessFilter, PantryItem


def _days_remaining(estimated_shelf_days: int | None, added_date: datetime, now: datetime) -> int | None:
    if estimated_shelf_days is None:
        return None
    return estimated_shelf_days - (now.date() - added_date.date()).days


def _row_to_item(row: Any, now: datetime) -> PantryItem:
    added_date = parse_sqlite_timestamp(row["added_date"])
    last_seen_date = parse_sqlite_timestamp(row["last_seen_date"])
    return PantryItem(
        id=row["id"],
        name=row["name"],
        quantity=row["quantity"],
        unit=row["unit"],
        category=row["category"],
        freshness_status=row["freshness_status"],
        estimated_shelf_days=row["estimated_shelf_days"],
        days_remaining=_days_remaining(row["estimated_shelf_days"], added_date, now),
        added_date=added_date,
        last_seen_date=last_seen_date,
        source=row["source"],
    )


async def get_pantry(
    category: str | None = None,
    freshness_filter: FreshnessFilter = "all",
    search: str | None = None,
    pantry_db: Database | None = None,
) -> list[PantryItem]:
    """Returns pantry items matching every given filter, each with
    days_remaining computed from estimated_shelf_days and added_date.

    freshness_filter:
        "all" — no freshness filtering at all.
        "fresh" — only items whose stored freshness_status is "fresh".
        "expiring_soon" — only items whose days_remaining is known and
        at or below settings.expiring_soon_days (this includes items
        already past their estimated shelf life, i.e. days_remaining <= 0
        — those need attention at least as urgently as ones still
        counting down). Items with no known estimated_shelf_days are
        excluded from this filter, since there's nothing to compare.

    search matches as a case-insensitive substring against the item's
    stored (canonical) name, after running the search term through the
    same normalizer pantry names are stored under.
    """
    pantry_db = pantry_db or get_pantry_db()

    query = "SELECT * FROM pantry WHERE 1=1"
    params: list[Any] = []
    if category is not None:
        query += " AND category = ?"
        params.append(category)
    if search is not None:
        query += " AND name LIKE ?"
        params.append(f"%{normalize_ingredient(search)}%")
    query += " ORDER BY name"

    rows = await pantry_db.fetch_all(query, params)
    now = datetime.utcnow()

    items: list[PantryItem] = []
    for row in rows:
        item = _row_to_item(row, now)
        if freshness_filter == "fresh" and item.freshness_status != "fresh":
            continue
        if freshness_filter == "expiring_soon" and (
            item.days_remaining is None or item.days_remaining > settings.expiring_soon_days
        ):
            continue
        items.append(item)

    return items
