// Mirrors mealsight/pantry/shelf_life.py's own CATEGORY_DEFAULTS keys —
// the six categories the backend actually knows a real shelf-life
// default for. An item added with a category outside this list still
// works (resolve_shelf_life falls back to a conservative "unknown"
// default), but picking one of these six is what lets the backend
// derive a real, category-specific estimated_shelf_days rather than the
// generic fallback. THIS LIST MUST STAY IN SYNC with CATEGORY_DEFAULTS
// if that table's own keys ever change.
export const PANTRY_CATEGORIES = [
  'protein',
  'vegetable',
  'fruit',
  'dairy',
  'grain',
  'condiment',
] as const

export type PantryCategory = (typeof PANTRY_CATEGORIES)[number]
