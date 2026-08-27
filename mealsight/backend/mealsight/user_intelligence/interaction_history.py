"""record_interaction / get_interaction_history — every recommendation
request and its outcome, regardless of whether anything was ever
cooked. meal_history (mealsight.user_intelligence.meal_history) only
ever gets a row on a CONFIRMED cook (mealsight.api.routers.cook); this
is every REQUEST, successful or not, cookable or not, including a run
that found nothing usable at all.

TEXT ONLY, on purpose: no image or audio bytes are ever stored here,
anywhere — voice_transcript is the already-transcribed text, ingredients
_summary is a short description of what a photo yielded, both plain
strings. This keeps the table small and lets an ephemeral demo
deployment's SQLite file survive a restart without a media blob store
to manage. record_interaction prunes back down to settings.
max_interaction_history_rows after every insert, oldest first, so this
table can't grow unbounded on a long-running instance either.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import json
from typing import Any

from mealsight.config.settings import settings
from mealsight.db import get_user_db
from mealsight.db.connection import Database
from mealsight.user_intelligence._datetime_utils import parse_sqlite_timestamp
from mealsight.user_intelligence.models import InteractionRecord


def _row_to_interaction_record(row: Any) -> InteractionRecord:
    return InteractionRecord(
        id=row["id"],
        created_at=parse_sqlite_timestamp(row["created_at"]),
        trace_id=row["trace_id"],
        modalities=json.loads(row["modalities"]),
        text_input=row["text_input"],
        voice_transcript=row["voice_transcript"],
        ingredients_summary=row["ingredients_summary"],
        merged_constraints=json.loads(row["merged_constraints"])
        if row["merged_constraints"] is not None
        else None,
        recommended_recipe_id=row["recommended_recipe_id"],
        recommended_recipe_name=row["recommended_recipe_name"],
        any_cookable=bool(row["any_cookable"]),
        top_match_score=row["top_match_score"],
        final_response=row["final_response"],
    )


async def _prune_interaction_history(user_db: Database, *, max_rows: int) -> int:
    """Deletes every row beyond the most recent max_rows (by created_at,
    then id, both descending — id as the tiebreaker since two rows can
    share the same CURRENT_TIMESTAMP second). Returns how many rows were
    removed, purely for logging; 0 is the normal case on an instance
    that hasn't yet accumulated max_rows interactions.

    Counted with a SELECT COUNT(*) first rather than read off Database.
    execute's own return value — that's lastrowid (meaningful after an
    INSERT), not an affected-row count, and a DELETE has no lastrowid of
    its own to report here."""
    row = await user_db.fetch_one("SELECT COUNT(*) as count FROM interaction_history")
    total = row["count"] if row is not None else 0
    if total <= max_rows:
        return 0

    await user_db.execute(
        "DELETE FROM interaction_history WHERE id NOT IN ("
        "  SELECT id FROM interaction_history ORDER BY created_at DESC, id DESC LIMIT ?"
        ")",
        (max_rows,),
    )
    return total - max_rows


async def record_interaction(
    trace_id: str | None,
    modalities: list[str],
    text_input: str | None,
    voice_transcript: str | None,
    ingredients_summary: str | None,
    merged_constraints: dict[str, Any] | None,
    recommended_recipe_id: str | None,
    recommended_recipe_name: str | None,
    any_cookable: bool,
    top_match_score: float | None,
    final_response: str | None,
    user_db: Database | None = None,
) -> InteractionRecord:
    """Records one completed recommendation run — called from the
    agent's own present node (the last node in the graph) for every run,
    regardless of outcome, including a run that found nothing cookable
    or nothing usable at all. Retention (settings.
    max_interaction_history_rows) is enforced every time, right after
    the insert, so this never needs a separate scheduled sweep."""
    user_db = user_db or get_user_db()

    interaction_id = await user_db.execute(
        "INSERT INTO interaction_history "
        "(trace_id, modalities, text_input, voice_transcript, ingredients_summary, "
        "merged_constraints, recommended_recipe_id, recommended_recipe_name, any_cookable, "
        "top_match_score, final_response) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            trace_id,
            json.dumps(modalities),
            text_input,
            voice_transcript,
            ingredients_summary,
            json.dumps(merged_constraints) if merged_constraints is not None else None,
            recommended_recipe_id,
            recommended_recipe_name,
            int(any_cookable),
            top_match_score,
            final_response,
        ),
    )

    row = await user_db.fetch_one("SELECT * FROM interaction_history WHERE id = ?", (interaction_id,))
    assert row is not None  # just inserted, in the same connection
    record = _row_to_interaction_record(row)

    await _prune_interaction_history(user_db, max_rows=settings.max_interaction_history_rows)

    return record


async def get_interaction_history(
    days_back: int = 30,
    limit: int = 50,
    user_db: Database | None = None,
) -> list[InteractionRecord]:
    """Returns the most recent interactions within days_back, most
    recent first, capped at limit. An empty list, never an error, on an
    instance with no recorded interactions yet."""
    user_db = user_db or get_user_db()

    rows = await user_db.fetch_all(
        "SELECT * FROM interaction_history WHERE created_at >= datetime('now', ?) "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (f"-{days_back} days", limit),
    )
    return [_row_to_interaction_record(row) for row in rows]
