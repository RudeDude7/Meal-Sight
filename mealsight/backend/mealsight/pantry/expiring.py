"""flag_expiring — pantry items that need attention soon, sorted by
urgency, each with a suggested action.

Deterministic, no LLM calls. Reuses mealsight.pantry.query.get_pantry
for the actual days_remaining computation rather than recomputing it —
this module only filters, sorts, and decides what to suggest.
"""

from __future__ import annotations

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.pantry.models import ExpiringItem
from mealsight.pantry.query import get_pantry
from mealsight.pantry.shelf_life import CATEGORY_DEFAULTS

_ALREADY_EXPIRED_ACTION = "already expired — verify and discard if spoiled"
_USE_TODAY_ACTION = "use today"
_FREEZE_ACTION = "freeze to extend"


def _suggest_action(days_remaining: int, category: str) -> str:
    if days_remaining < 0:
        return _ALREADY_EXPIRED_ACTION
    if days_remaining <= 1:
        return _USE_TODAY_ACTION

    # Only worth suggesting a freeze when it would genuinely add time —
    # if this item's own category has no shelf_days_frozen value at all
    # (an egg's "protein" category, say), "freeze to extend" would be
    # misleading advice.
    default = CATEGORY_DEFAULTS.get(category.lower())
    if default is not None and default.shelf_days_frozen is not None:
        return _FREEZE_ACTION
    return f"use within {days_remaining} days"


async def flag_expiring(
    days_threshold: int | None = None, pantry_db: Database | None = None
) -> list[ExpiringItem]:
    """Returns every pantry item whose days_remaining is known and at or
    below days_threshold (settings.expiring_soon_days if not given),
    sorted by days_remaining ascending — an item already past its
    estimated shelf life (negative days_remaining) sorts first, ahead of
    anything still counting down, and gets its own distinct
    suggested_action rather than being folded into "use within N days".

    An empty pantry (or one with nothing meeting the threshold) returns
    an empty list, not an error.
    """
    threshold = days_threshold if days_threshold is not None else settings.expiring_soon_days

    items = await get_pantry(freshness_filter="all", pantry_db=pantry_db)

    results: list[ExpiringItem] = []
    for item in items:
        if item.days_remaining is None or item.days_remaining > threshold:
            continue
        results.append(
            ExpiringItem(
                name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                days_remaining=item.days_remaining,
                suggested_action=_suggest_action(item.days_remaining, item.category),
            )
        )

    results.sort(key=lambda item: item.days_remaining)
    return results
