"""log_waste / get_waste_stats — tracks food thrown out, with a reason,
and turns repeated waste of the same item into a specific, actionable
insight.

LOGGING WASTE ALWAYS DEDUCTS FROM THE PANTRY, IN THE SAME CALL: a user
throwing something out has already lost it — the pantry no longer has
it regardless of whether anything gets logged. Requiring a caller to
make two separate calls (log_waste, then remove_items) would only ever
invite the two to drift out of sync (a waste event logged with no
matching pantry deduction, or a deduction with no waste reason ever
recorded) for no real benefit; nothing about "record why this was
wasted" and "the pantry has less of it now" is actually a separate
decision a caller should get to make independently. log_waste calls
mealsight.pantry.remove.remove_items directly (the exact same clamped-
removal logic every other removal path uses, writing the same
consumption_log entry it always would) rather than reimplementing any
of that here.

estimated_cost (a real column in waste_log, per the original spec) has
no price data anywhere in this project — no product-price table, no
grocery-cost API, nothing. This module never writes a non-null value
into it. The column stays in the schema (deleting it would be
inventing a scope decision nobody made) but is simply never populated;
a future phase with real price data can start writing it without a
migration.

Canonicalization: item_name is resolved through the exact same
normalize_ingredient + resolve_canonical pipeline every other pantry
function uses, so "scallions" and "green onion" accumulate against one
waste_log identity rather than splitting a count that insights and
stats both depend on being accurate.

Deterministic except for the pantry deduction it delegates to
remove_items (itself deterministic); no LLM calls anywhere in this
module.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import get_args

from mealsight.config.settings import settings
from mealsight.db import get_pantry_db, get_recipe_db
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.pantry._datetime_utils import parse_sqlite_timestamp
from mealsight.pantry.models import (
    MostWastedItem,
    RemovalItemInput,
    WasteLogResult,
    WasteReason,
    WasteStats,
    WasteTimeRange,
    WasteTrend,
)
from mealsight.pantry.remove import remove_items

WASTE_REASONS: frozenset[str] = frozenset(get_args(WasteReason))

# Matches mealsight.pantry._datetime_utils._SQLITE_TIMESTAMP_FORMAT
# exactly — logged_at is a plain TEXT column (no PARSE_DECLTYPES), so a
# datetime bound as a query parameter must be pre-formatted to this
# exact shape for a lexicographic string comparison against it to mean
# what it looks like it means; binding a raw datetime object and
# relying on sqlite3's own (deprecated as of 3.12, and never quite the
# same format anyway — it includes microseconds) default adapter would
# risk an off-by-a-fraction-of-a-second boundary mismatch.
_QUERY_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _for_query(value: datetime) -> str:
    return value.strftime(_QUERY_TIMESTAMP_FORMAT)

# "A handful" — the task's own explicit framing for the minimum sample
# size a trend comparison needs before a percentage means anything.
# Applied to BOTH the current and the previous period: if either has
# fewer entries than this, the comparison is reported as insufficient
# rather than a real (and potentially wildly noisy, e.g. "300% up"
# off a base of one) percentage.
MIN_ENTRIES_FOR_TREND = 5

# One documented place reasons map to a concrete, actionable suggestion
# — paired with _REASON_LABELS (the human-readable phrase used inside
# the generated insight sentence itself).
_REASON_SUGGESTIONS: dict[str, str] = {
    "expired": "buying smaller amounts or keeping extra in the freezer",
    "spoiled": "buying smaller amounts or checking on it more often",
    "didn_t_like": "leaving it off the list next time",
    "too_much": "buying smaller amounts",
}

_REASON_LABELS: dict[str, str] = {
    "expired": "expired",
    "spoiled": "spoiled",
    "didn_t_like": "not liked",
    "too_much": "bought too much",
}


class InvalidWasteReasonError(ValueError):
    """Raised by log_waste when reason isn't one of WASTE_REASONS."""


def _dominant_reason(reasons: list[str]) -> str:
    # Counter.most_common ties break on first-inserted order, which for
    # a chronologically-appended list of waste_log rows means the
    # earliest-occurring reason among the tied ones wins — a reasonable,
    # deterministic tiebreak, not an arbitrary one.
    return Counter(reasons).most_common(1)[0][0]


def _build_insight(item_name: str, count: int, reasons: list[str]) -> str:
    dominant = _dominant_reason(reasons)
    all_same = len(set(reasons)) == 1
    reason_clause = f"all {_REASON_LABELS[dominant]}" if all_same else f"mostly {_REASON_LABELS[dominant]}"
    suggestion = _REASON_SUGGESTIONS[dominant]
    times = "time" if count == 1 else "times"
    return (
        f"You've thrown away {item_name} {count} {times}, {reason_clause} — consider {suggestion}."
    )


async def log_waste(
    item_name: str,
    quantity_wasted: float,
    unit: str | None,
    reason: str,
    pantry_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> WasteLogResult:
    """Logs one instance of item_name being thrown out, deducts
    quantity_wasted from the pantry in the same call (see this module's
    own docstring for why that's not a separate step), and returns an
    insight once this item has reached settings.waste_insight_threshold
    total logged instances (all-time) — else insight is null.

    Raises InvalidWasteReasonError, naming the accepted values, if
    reason isn't one of WASTE_REASONS.
    """
    if reason not in WASTE_REASONS:
        raise InvalidWasteReasonError(
            f"{reason!r} is not a recognized waste reason. Accepted values: {sorted(WASTE_REASONS)}."
        )

    pantry_db = pantry_db or get_pantry_db()
    if synonym_map is None:
        synonym_map = await load_synonym_map(get_recipe_db())

    canonical = resolve_canonical(normalize_ingredient(item_name), synonym_map)

    removal_result = await remove_items(
        [RemovalItemInput(name=canonical, quantity_used=quantity_wasted)],
        pantry_db=pantry_db,
        synonym_map=synonym_map,
    )
    removal_detail = removal_result.details[0]

    row_id = await pantry_db.execute(
        "INSERT INTO waste_log (item_name, quantity_wasted, unit, reason) VALUES (?, ?, ?, ?)",
        (canonical, quantity_wasted, unit, reason),
    )

    reason_rows = await pantry_db.fetch_all(
        "SELECT reason FROM waste_log WHERE item_name = ?", (canonical,)
    )
    all_reasons = [row["reason"] for row in reason_rows]
    count = len(all_reasons)

    insight = (
        _build_insight(canonical, count, all_reasons) if count >= settings.waste_insight_threshold else None
    )

    logged_at_row = await pantry_db.fetch_one("SELECT logged_at FROM waste_log WHERE id = ?", (row_id,))
    assert logged_at_row is not None  # just inserted, in the same connection
    logged_at = parse_sqlite_timestamp(logged_at_row["logged_at"])

    return WasteLogResult(
        id=row_id,
        item_name=item_name,
        canonical_name=canonical,
        quantity_wasted=quantity_wasted,
        unit=unit,
        reason=reason,  # type: ignore[arg-type]
        logged_at=logged_at,
        removal=removal_detail,
        insight=insight,
    )


def _period_bounds(
    time_range: WasteTimeRange, current_time: datetime
) -> tuple[datetime, datetime | None]:
    """Returns (current_period_start, previous_period_start), where
    previous_period_start is None for all_time (no previous period
    exists). The current period always runs from its own start through
    current_time; the previous period runs from previous_period_start
    through current_period_start (exclusive)."""
    if time_range == "this_week":
        start_of_week = (current_time - timedelta(days=current_time.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return start_of_week, start_of_week - timedelta(days=7)
    if time_range == "this_month":
        start_of_month = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_month_end = start_of_month - timedelta(days=1)
        start_of_previous_month = previous_month_end.replace(day=1)
        return start_of_month, start_of_previous_month
    return datetime.min, None


async def get_waste_stats(
    time_range: WasteTimeRange,
    current_time: datetime | None = None,
    pantry_db: Database | None = None,
) -> WasteStats:
    """Returns total_items_wasted (a count of logged waste EVENTS in
    time_range, not a quantity sum — quantities can be in incompatible
    units, e.g. "2 cups" and "3 count", so summing them would be
    meaningless), most_wasted (ranked by count within time_range, each
    with its dominant reason within that same window), a trend against
    the immediately preceding equivalent period (null change_pct, with
    an explanatory message, below MIN_ENTRIES_FOR_TREND entries in
    either period — see that constant's own docstring), and
    active_insights (every item currently at or above settings.
    waste_insight_threshold, ALWAYS computed all-time regardless of
    time_range — see WasteStats' own docstring for why).
    """
    pantry_db = pantry_db or get_pantry_db()
    current_time = current_time or datetime.now()

    current_start, previous_start = _period_bounds(time_range, current_time)

    current_rows = await pantry_db.fetch_all(
        "SELECT item_name, reason FROM waste_log WHERE logged_at >= ?", (_for_query(current_start),)
    )
    total_items_wasted = len(current_rows)

    items_by_name: dict[str, list[str]] = {}
    for row in current_rows:
        items_by_name.setdefault(row["item_name"], []).append(row["reason"])

    most_wasted = [
        MostWastedItem(item_name=name, count=len(reasons), dominant_reason=_dominant_reason(reasons))  # type: ignore[arg-type]
        for name, reasons in items_by_name.items()
    ]
    most_wasted.sort(key=lambda entry: entry.count, reverse=True)

    trend = await _compute_trend(pantry_db, time_range, current_start, previous_start, total_items_wasted)

    active_insights = await _compute_active_insights(pantry_db)

    return WasteStats(
        time_range=time_range,
        total_items_wasted=total_items_wasted,
        most_wasted=most_wasted,
        trend=trend,
        active_insights=active_insights,
    )


async def _compute_trend(
    pantry_db: Database,
    time_range: WasteTimeRange,
    current_start: datetime,
    previous_start: datetime | None,
    current_period_count: int,
) -> WasteTrend:
    if time_range == "all_time" or previous_start is None:
        return WasteTrend(
            current_period_count=current_period_count,
            previous_period_count=0,
            change_pct=None,
            message="all_time has no previous period to compare against.",
        )

    previous_rows = await pantry_db.fetch_all(
        "SELECT id FROM waste_log WHERE logged_at >= ? AND logged_at < ?",
        (_for_query(previous_start), _for_query(current_start)),
    )
    previous_period_count = len(previous_rows)

    if current_period_count < MIN_ENTRIES_FOR_TREND or previous_period_count < MIN_ENTRIES_FOR_TREND:
        return WasteTrend(
            current_period_count=current_period_count,
            previous_period_count=previous_period_count,
            change_pct=None,
            message=(
                f"Not enough data yet for a meaningful trend — fewer than {MIN_ENTRIES_FOR_TREND} "
                "entries in the current or previous period."
            ),
        )

    change_pct = ((current_period_count - previous_period_count) / previous_period_count) * 100
    period_label = "week" if time_range == "this_week" else "month"
    direction = "up" if change_pct >= 0 else "down"
    message = f"{direction} {abs(change_pct):.0f}% from last {period_label}."
    return WasteTrend(
        current_period_count=current_period_count,
        previous_period_count=previous_period_count,
        change_pct=change_pct,
        message=message,
    )


async def _compute_active_insights(pantry_db: Database) -> list[str]:
    rows = await pantry_db.fetch_all("SELECT item_name, reason FROM waste_log")
    items_by_name: dict[str, list[str]] = {}
    for row in rows:
        items_by_name.setdefault(row["item_name"], []).append(row["reason"])

    insights = [
        _build_insight(name, len(reasons), reasons)
        for name, reasons in items_by_name.items()
        if len(reasons) >= settings.waste_insight_threshold
    ]
    insights.sort()
    return insights
