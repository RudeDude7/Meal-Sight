"""Tests for mealsight.pantry.waste.log_waste and get_waste_stats."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from mealsight.db.connection import Database
from mealsight.pantry.models import PantryItemInput
from mealsight.pantry.update import update_pantry
from mealsight.pantry.waste import (
    MIN_ENTRIES_FOR_TREND,
    InvalidWasteReasonError,
    get_waste_stats,
    log_waste,
)


async def _seed_pantry_item(pantry_db: Database, name: str, quantity: float) -> None:
    await update_pantry(
        [PantryItemInput(name=name, quantity=quantity, unit="count", category="vegetable")],
        pantry_db=pantry_db,
        synonym_map={},
    )


# --------------------------------------------------------------------
# reason validation
# --------------------------------------------------------------------


async def test_reason_validation_rejects_unknown_values(pantry_db: Database) -> None:
    with pytest.raises(InvalidWasteReasonError):
        await log_waste("spinach", 1.0, "bag", "not_a_real_reason", pantry_db=pantry_db, synonym_map={})


@pytest.mark.parametrize("reason", ["expired", "spoiled", "didn_t_like", "too_much"])
async def test_reason_validation_accepts_every_documented_value(pantry_db: Database, reason: str) -> None:
    result = await log_waste("spinach", 1.0, "bag", reason, pantry_db=pantry_db, synonym_map={})
    assert result.reason == reason


# --------------------------------------------------------------------
# canonicalization
# --------------------------------------------------------------------


async def test_canonically_equivalent_names_accumulate_as_one_item(pantry_db: Database) -> None:
    # Keyed by the NORMALIZED synonym form ("scallions" -> "scallion" via
    # normalize_ingredient's own singularization) mapping to the
    # normalized canonical form — resolve_canonical looks up the
    # already-normalized string, never the raw input.
    synonym_map = {"scallion": "green onion"}

    await log_waste("scallions", 1.0, "bunch", "expired", pantry_db=pantry_db, synonym_map=synonym_map)
    result = await log_waste(
        "green onion", 1.0, "bunch", "expired", pantry_db=pantry_db, synonym_map=synonym_map
    )

    assert result.canonical_name == "green onion"
    rows = await pantry_db.fetch_all("SELECT item_name FROM waste_log ORDER BY id")
    assert [row["item_name"] for row in rows] == ["green onion", "green onion"]


# --------------------------------------------------------------------
# pantry deduction happens in the same call
# --------------------------------------------------------------------


async def test_logging_waste_deducts_the_pantry_in_the_same_call(pantry_db: Database) -> None:
    await _seed_pantry_item(pantry_db, "spinach", 5.0)

    result = await log_waste("spinach", 2.0, "count", "spoiled", pantry_db=pantry_db, synonym_map={})

    assert result.removal.found is True
    assert result.removal.quantity_removed == 2.0
    row = await pantry_db.fetch_one("SELECT quantity FROM pantry WHERE name = 'spinach'")
    assert row is not None
    assert row["quantity"] == 3.0


async def test_logging_waste_for_an_item_not_in_the_pantry_still_logs_it(pantry_db: Database) -> None:
    result = await log_waste("unobtainium", 1.0, "count", "expired", pantry_db=pantry_db, synonym_map={})

    assert result.removal.found is False
    rows = await pantry_db.fetch_all("SELECT * FROM waste_log")
    assert len(rows) == 1


async def test_consumption_log_is_written_via_the_shared_removal_path(pantry_db: Database) -> None:
    await _seed_pantry_item(pantry_db, "spinach", 5.0)

    await log_waste("spinach", 2.0, "count", "spoiled", pantry_db=pantry_db, synonym_map={})

    row = await pantry_db.fetch_one("SELECT quantity_used FROM consumption_log WHERE item_name = 'spinach'")
    assert row is not None
    assert row["quantity_used"] == 2.0


# --------------------------------------------------------------------
# insight generation
# --------------------------------------------------------------------


async def test_insight_fires_exactly_at_the_threshold_and_not_before(pantry_db: Database) -> None:
    # settings.waste_insight_threshold defaults to 3.
    first = await log_waste("spinach", 1.0, "bag", "expired", pantry_db=pantry_db, synonym_map={})
    second = await log_waste("spinach", 1.0, "bag", "expired", pantry_db=pantry_db, synonym_map={})
    third = await log_waste("spinach", 1.0, "bag", "expired", pantry_db=pantry_db, synonym_map={})

    assert first.insight is None
    assert second.insight is None
    assert third.insight is not None


async def test_insight_text_names_the_real_item_count_and_dominant_reason(pantry_db: Database) -> None:
    for _ in range(3):
        result = await log_waste("spinach", 1.0, "bag", "expired", pantry_db=pantry_db, synonym_map={})

    assert result.insight is not None
    assert "spinach" in result.insight
    assert "3" in result.insight
    assert "expired" in result.insight


async def test_insight_reflects_a_mixed_dominant_reason_not_a_forced_all(pantry_db: Database) -> None:
    await log_waste("spinach", 1.0, "bag", "expired", pantry_db=pantry_db, synonym_map={})
    await log_waste("spinach", 1.0, "bag", "expired", pantry_db=pantry_db, synonym_map={})
    result = await log_waste("spinach", 1.0, "bag", "spoiled", pantry_db=pantry_db, synonym_map={})

    assert result.insight is not None
    assert "mostly expired" in result.insight
    assert "all expired" not in result.insight


# --------------------------------------------------------------------
# get_waste_stats: time_range window filtering
# --------------------------------------------------------------------


async def _log_at(pantry_db: Database, name: str, reason: str, logged_at: datetime) -> None:
    await pantry_db.execute(
        "INSERT INTO waste_log (item_name, quantity_wasted, unit, reason, logged_at) VALUES (?, ?, ?, ?, ?)",
        (name, 1.0, "count", reason, logged_at.strftime("%Y-%m-%d %H:%M:%S")),
    )


async def test_this_week_excludes_entries_from_before_the_current_week(pantry_db: Database) -> None:
    now = datetime(2026, 1, 8, 12, 0)  # a Thursday
    # Matches _period_bounds' own boundary exactly: midnight of the
    # current week's Monday, not just "7 days back at the same time".
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    await _log_at(pantry_db, "spinach", "expired", now)
    await _log_at(pantry_db, "spinach", "expired", start_of_week - timedelta(minutes=1))

    stats = await get_waste_stats("this_week", current_time=now, pantry_db=pantry_db)
    assert stats.total_items_wasted == 1


async def test_this_month_excludes_entries_from_the_previous_month(pantry_db: Database) -> None:
    now = datetime(2026, 3, 15, 12, 0)
    await _log_at(pantry_db, "spinach", "expired", now)
    await _log_at(pantry_db, "spinach", "expired", datetime(2026, 2, 28, 23, 59))

    stats = await get_waste_stats("this_month", current_time=now, pantry_db=pantry_db)
    assert stats.total_items_wasted == 1


async def test_all_time_includes_everything(pantry_db: Database) -> None:
    now = datetime(2026, 3, 15, 12, 0)
    await _log_at(pantry_db, "spinach", "expired", now)
    await _log_at(pantry_db, "spinach", "expired", datetime(2020, 1, 1, 0, 0))

    stats = await get_waste_stats("all_time", current_time=now, pantry_db=pantry_db)
    assert stats.total_items_wasted == 2


async def test_most_wasted_is_ranked_by_count_with_dominant_reason(pantry_db: Database) -> None:
    now = datetime(2026, 3, 15, 12, 0)
    for _ in range(3):
        await _log_at(pantry_db, "spinach", "expired", now)
    await _log_at(pantry_db, "banana", "spoiled", now)

    stats = await get_waste_stats("all_time", current_time=now, pantry_db=pantry_db)

    assert stats.most_wasted[0].item_name == "spinach"
    assert stats.most_wasted[0].count == 3
    assert stats.most_wasted[0].dominant_reason == "expired"
    assert stats.most_wasted[1].item_name == "banana"


# --------------------------------------------------------------------
# get_waste_stats: trend
# --------------------------------------------------------------------


async def test_trend_reports_insufficient_data_below_the_threshold(pantry_db: Database) -> None:
    now = datetime(2026, 3, 15, 12, 0)  # a Sunday
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    # Fewer than MIN_ENTRIES_FOR_TREND in the current week.
    for _ in range(MIN_ENTRIES_FOR_TREND - 1):
        await _log_at(pantry_db, "spinach", "expired", now)
    # Plenty in the previous week — still insufficient overall, since
    # BOTH periods must clear the threshold.
    for _ in range(MIN_ENTRIES_FOR_TREND + 2):
        await _log_at(pantry_db, "spinach", "expired", start_of_week - timedelta(days=1))

    stats = await get_waste_stats("this_week", current_time=now, pantry_db=pantry_db)
    assert stats.trend.change_pct is None
    assert "not enough data" in stats.trend.message.lower()


async def test_trend_computes_a_real_percentage_once_both_periods_clear_the_threshold(
    pantry_db: Database,
) -> None:
    now = datetime(2026, 3, 15, 12, 0)  # a Sunday
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    for _ in range(10):
        await _log_at(pantry_db, "spinach", "expired", now)
    for _ in range(5):
        await _log_at(pantry_db, "spinach", "expired", start_of_week - timedelta(days=1))

    stats = await get_waste_stats("this_week", current_time=now, pantry_db=pantry_db)
    assert stats.trend.current_period_count == 10
    assert stats.trend.previous_period_count == 5
    assert stats.trend.change_pct == 100.0
    assert "up" in stats.trend.message.lower()


async def test_all_time_trend_has_no_previous_period(pantry_db: Database) -> None:
    now = datetime(2026, 3, 15, 12, 0)
    for _ in range(10):
        await _log_at(pantry_db, "spinach", "expired", now)

    stats = await get_waste_stats("all_time", current_time=now, pantry_db=pantry_db)
    assert stats.trend.change_pct is None
    assert stats.trend.previous_period_count == 0


# --------------------------------------------------------------------
# get_waste_stats: active_insights (always all-time)
# --------------------------------------------------------------------


async def test_active_insights_are_computed_all_time_regardless_of_time_range(pantry_db: Database) -> None:
    now = datetime(2026, 3, 15, 12, 0)
    # All three entries are outside the current week, so this_week's own
    # total_items_wasted is 0 — but active_insights must still surface
    # the standing pattern, since it's always all-time.
    for _ in range(3):
        await _log_at(pantry_db, "spinach", "expired", datetime(2020, 1, 1, 0, 0))

    stats = await get_waste_stats("this_week", current_time=now, pantry_db=pantry_db)
    assert stats.total_items_wasted == 0
    assert len(stats.active_insights) == 1
    assert "spinach" in stats.active_insights[0]


async def test_no_active_insights_below_the_threshold(pantry_db: Database) -> None:
    now = datetime(2026, 3, 15, 12, 0)
    await _log_at(pantry_db, "spinach", "expired", now)

    stats = await get_waste_stats("all_time", current_time=now, pantry_db=pantry_db)
    assert stats.active_insights == []


# --------------------------------------------------------------------
# fresh database
# --------------------------------------------------------------------


async def test_a_fresh_database_gets_the_waste_log_table_via_startup_init(pantry_db: Database) -> None:
    # pantry_db (this file's own fixture) is exactly what a fresh
    # deployment's own startup schema init produces — see tests/
    # test_pantry/conftest.py's own pantry_db fixture, which runs
    # init_database against pantry.sql the same way mealsight.
    # mcp_servers.pantry_manager.__main__._initialize_schema does at
    # real server startup.
    row = await pantry_db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'waste_log'"
    )
    assert row is not None
