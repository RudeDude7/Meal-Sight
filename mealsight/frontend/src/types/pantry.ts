// Mirrors mealsight/pantry/models.py.

import type { Importance } from '@/types/matching'

export type FreshnessFilter = 'expiring_soon' | 'fresh' | 'all'

export type GrocerySection =
  'produce' | 'protein' | 'dairy' | 'bakery' | 'pantry' | 'frozen' | 'spices' | 'other'

/** The input shape for PATCH /api/pantry. */
export interface PantryItemInput {
  name: string
  quantity: number | null
  unit: string | null
  category: string
  freshness_status?: string
}

/**
 * One row of the pantry table, as returned by GET /api/pantry.
 * days_remaining is null when estimated_shelf_days itself is unknown.
 */
export interface PantryItem {
  id: number
  name: string
  quantity: number | null
  unit: string | null
  category: string
  freshness_status: string
  estimated_shelf_days: number | null
  days_remaining: number | null
  added_date: string
  last_seen_date: string
  source: string
}

export interface PantryChangeDetail {
  name: string
  canonical_name: string
  action: 'added' | 'updated'
  quantity_after: number | null
}

/** A pre-existing pantry item not seen in a while. */
export interface FlaggedPantryItem {
  id: number
  name: string
  last_seen_date: string
  days_since_seen: number
}

export interface PantryUpdateResult {
  added_count: number
  updated_count: number
  flagged_count: number
  details: PantryChangeDetail[]
  flagged_items: FlaggedPantryItem[]
}

export interface RemovalDetail {
  name: string
  canonical_name: string
  found: boolean
  quantity_requested: number
  quantity_removed: number
  quantity_remaining: number
  discrepancy: number
  deleted: boolean
}

export interface RemovalResult {
  details: RemovalDetail[]
}

/** One pantry item flagged as expiring soon, sorted most-urgent first. */
export interface ExpiringItem {
  name: string
  quantity: number | null
  unit: string | null
  days_remaining: number
  suggested_action: string
}

export interface GroceryQuantity {
  quantity: number | null
  unit: string | null
}

/** One grocery-list line: one canonical ingredient, aggregated across recipes. */
export interface GroceryListItem {
  name: string
  quantities: GroceryQuantity[]
  needed_for: string[]
  importance: Importance
  section: GrocerySection
  is_staple: boolean
  verify_note: string | null
  checked: boolean
}

export interface GroceryListSection {
  section: GrocerySection
  items: GroceryListItem[]
}

/** A full grocery list, as returned by GET /api/grocery-list. */
export interface GroceryList {
  id: number
  status: string
  created_at: string
  sections: GroceryListSection[]
}

export type WasteReason = 'expired' | 'spoiled' | 'didn_t_like' | 'too_much'

export type WasteTimeRange = 'this_week' | 'this_month' | 'all_time'

/** The input shape for POST /api/waste. */
export interface LogWasteInput {
  item_name: string
  quantity_wasted: number
  unit: string | null
  reason: WasteReason
}

/**
 * What POST /api/waste returns. insight is null unless this item has
 * now been logged as wasted the backend's own configured threshold
 * times or more (all-time) — see mealsight.pantry.waste.
 */
export interface WasteLogResult {
  id: number
  item_name: string
  canonical_name: string
  quantity_wasted: number
  unit: string | null
  reason: WasteReason
  logged_at: string
  removal: RemovalDetail
  insight: string | null
}

export interface MostWastedItem {
  item_name: string
  count: number
  dominant_reason: WasteReason
}

export interface WasteTrend {
  current_period_count: number
  previous_period_count: number
  change_pct: number | null
  message: string
}

/** What GET /api/waste returns. active_insights is always all-time, independent of time_range. */
export interface WasteStats {
  time_range: WasteTimeRange
  total_items_wasted: number
  most_wasted: MostWastedItem[]
  trend: WasteTrend
  active_insights: string[]
}
