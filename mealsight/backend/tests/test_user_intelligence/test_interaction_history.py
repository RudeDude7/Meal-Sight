"""Tests for mealsight.user_intelligence.interaction_history: recording,
reading back most-recent-first, and retention pruning. user_db is the
fresh-per-test Database fixture from this directory's own conftest.py.
"""

from __future__ import annotations

import pytest

from mealsight.config.settings import settings
from mealsight.db.connection import Database
from mealsight.user_intelligence.interaction_history import (
    get_interaction_history,
    record_interaction,
)


async def _record(
    user_db: Database,
    *,
    trace_id: str = "t1",
    modalities: list[str] | None = None,
    recommended_recipe_id: str | None = None,
    any_cookable: bool = False,
    top_match_score: float | None = None,
    final_response: str | None = "done",
) -> None:
    await record_interaction(
        trace_id,
        modalities or ["text"],
        "something quick",
        None,
        None,
        None,
        recommended_recipe_id,
        None,
        any_cookable,
        top_match_score,
        final_response,
        user_db=user_db,
    )


async def test_record_interaction_with_no_cookable_recipe_still_records_a_row(user_db: Database) -> None:
    await _record(user_db, any_cookable=False, recommended_recipe_id=None, top_match_score=0.3)

    history = await get_interaction_history(user_db=user_db)

    assert len(history) == 1
    assert history[0].any_cookable is False
    assert history[0].recommended_recipe_id is None
    assert history[0].top_match_score == 0.3


async def test_media_bytes_are_never_stored(user_db: Database) -> None:
    await record_interaction(
        "t1",
        ["vision", "audio"],
        None,
        "a real transcript, plain text",
        "Found 3 item(s): egg, milk, butter",
        None,
        None,
        None,
        False,
        None,
        "nothing cookable",
        user_db=user_db,
    )

    row = await user_db.fetch_one("SELECT * FROM interaction_history LIMIT 1")
    assert row is not None
    # Every column in this table is a plain scalar (TEXT/INTEGER/REAL) —
    # there is no column any raw image/audio bytes could even go into,
    # confirmed here by checking every value is a str, int, float, or
    # None, never a bytes object.
    for value in dict(row).values():
        assert not isinstance(value, bytes)


async def test_get_interaction_history_returns_most_recent_first(user_db: Database) -> None:
    await _record(user_db, trace_id="first")
    await _record(user_db, trace_id="second")
    await _record(user_db, trace_id="third")

    history = await get_interaction_history(user_db=user_db)

    assert [record.trace_id for record in history] == ["third", "second", "first"]


async def test_get_interaction_history_respects_limit(user_db: Database) -> None:
    for i in range(5):
        await _record(user_db, trace_id=str(i))

    history = await get_interaction_history(limit=2, user_db=user_db)

    assert len(history) == 2
    assert [record.trace_id for record in history] == ["4", "3"]


async def test_retention_prunes_beyond_the_configured_cap(
    user_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_interaction_history_rows", 3)

    for i in range(5):
        await _record(user_db, trace_id=str(i))

    total = await user_db.fetch_one("SELECT COUNT(*) as count FROM interaction_history")
    assert total is not None
    assert total["count"] == 3

    history = await get_interaction_history(limit=10, user_db=user_db)
    # The three most recently inserted survive; the two oldest were pruned.
    assert [record.trace_id for record in history] == ["4", "3", "2"]
