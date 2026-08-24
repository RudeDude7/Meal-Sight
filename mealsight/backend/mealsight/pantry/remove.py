"""remove_items — decrements pantry quantities (from cooking, spoilage,
or any other consumption) and logs every removal to consumption_log.

Deterministic, no LLM calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mealsight.db import get_pantry_db, get_recipe_db
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.pantry.models import RemovalDetail, RemovalItemInput, RemovalResult


async def remove_items(
    items: Sequence[RemovalItemInput],
    pantry_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> RemovalResult:
    """Removes quantity_used of each item from the pantry.

    Removing more than is actually present clamps at zero rather than
    going negative: quantity_removed is capped at whatever was really
    there, and discrepancy reports how much of the request that clamp
    had to drop (0 when the full amount was available). A row whose
    quantity reaches zero or below is deleted outright, not left sitting
    at 0. Every removal — clamped or not — is recorded in
    consumption_log, with used_for_recipe when supplied.

    An item not found in the pantry at all is reported with found=False
    and the entire requested quantity as the discrepancy, and is not
    logged to consumption_log (there is nothing real to log removing).
    """
    pantry_db = pantry_db or get_pantry_db()
    if synonym_map is None:
        synonym_map = await load_synonym_map(get_recipe_db())

    details: list[RemovalDetail] = []

    for item in items:
        canonical = resolve_canonical(normalize_ingredient(item.name), synonym_map)
        existing = await pantry_db.fetch_one("SELECT id, quantity FROM pantry WHERE name = ?", (canonical,))

        if existing is None:
            details.append(
                RemovalDetail(
                    name=item.name,
                    canonical_name=canonical,
                    found=False,
                    quantity_requested=item.quantity_used,
                    quantity_removed=0.0,
                    quantity_remaining=0.0,
                    discrepancy=item.quantity_used,
                    deleted=False,
                )
            )
            continue

        available = existing["quantity"] or 0.0
        actual_removed = min(item.quantity_used, available)
        remaining = available - actual_removed
        discrepancy = item.quantity_used - actual_removed
        deleted = remaining <= 0

        if deleted:
            await pantry_db.execute("DELETE FROM pantry WHERE id = ?", (existing["id"],))
        else:
            await pantry_db.execute(
                "UPDATE pantry SET quantity = ? WHERE id = ?", (remaining, existing["id"])
            )

        await pantry_db.execute(
            "INSERT INTO consumption_log (item_name, quantity_used, used_for_recipe) VALUES (?, ?, ?)",
            (canonical, actual_removed, item.used_for_recipe),
        )

        details.append(
            RemovalDetail(
                name=item.name,
                canonical_name=canonical,
                found=True,
                quantity_requested=item.quantity_used,
                quantity_removed=actual_removed,
                quantity_remaining=max(remaining, 0.0),
                discrepancy=discrepancy,
                deleted=deleted,
            )
        )

    return RemovalResult(details=details)
