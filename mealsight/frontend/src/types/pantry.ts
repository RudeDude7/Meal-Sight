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
