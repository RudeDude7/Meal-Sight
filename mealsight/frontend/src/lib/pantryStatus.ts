// Mirrors mealsight/config/settings.py's own stale_pantry_item_days
// (14) — a single fixed number, unlike suggested_action's own category-
// default table, so mirroring it here carries none of that drift risk:
// mealsight/pantry/update.py's own _find_stale_items does the exact
// same "days since last_seen_date > threshold" comparison this does,
// against the exact same field GET /api/pantry already returns.
export const STALE_THRESHOLD_DAYS = 14

export function daysSinceLastSeen(lastSeenDate: string): number {
  const then = new Date(lastSeenDate).getTime()
  if (Number.isNaN(then)) return 0
  const now = Date.now()
  return Math.floor((now - then) / (1000 * 60 * 60 * 24))
}

export function isStale(lastSeenDate: string): boolean {
  return daysSinceLastSeen(lastSeenDate) > STALE_THRESHOLD_DAYS
}
