// Mirrors mealsight/matching/models.py.

export type Importance = 'critical' | 'important' | 'optional'
export type FlavorImpact = 'minimal' | 'noticeable' | 'significant'

/** A recipe ingredient the pantry has an exact canonical match for. */
export interface MatchedItem {
  name: string
  importance: Importance
}

/** A recipe ingredient with no direct match, but an eligible substitute on hand. */
export interface SubstitutableItem {
  original: string
  substitute: string
  ratio: string
  flavor_impact: FlavorImpact
  importance: Importance
}

/** A recipe ingredient with neither a direct match nor an eligible substitute. */
export interface MissingItem {
  name: string
  importance: Importance
}

/**
 * A recipe ingredient the pantry only has a less specific form of (the
 * recipe wants "chicken thighs", the pantry only has "chicken").
 */
export interface PartialMatchItem {
  name: string
  pantry_match: string
  importance: Importance
  note: string
}

/** The full result of matching one recipe against one pantry. */
export interface MatchResult {
  match_score: number
  can_cook: boolean
  matched_items: MatchedItem[]
  substitutable_items: SubstitutableItem[]
  partial_matches: PartialMatchItem[]
  missing_items: MissingItem[]
  critical_missing: string[]
  summary: string
}
