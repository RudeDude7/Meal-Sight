// Mirrors mealsight/api/routers/recommend.py (RecommendationAccepted,
// _serialize_result's own field set) and the internal shapes
// mealsight/agent/nodes/reason.py and present.py build into
// state["top_recommendation"] / state["processing_trace"]. Those two
// are plain dicts on the wire (MealSightState types them as
// dict[str, Any]) rather than dedicated pydantic response models, so
// the fields below are typed from reading reason.py/present.py
// directly rather than from a schema — anything not read explicitly
// falls under the trailing index signature.

import type { ScaledRecipe } from '@/types/recipe'
import type { GroceryList } from '@/types/pantry'
import type { NutritionResult } from '@/types/recipe'

/** What POST /api/recommend returns immediately (202 Accepted). */
export interface RecommendationAccepted {
  session_id: string
  status: string
  websocket_url: string
}

export interface DimensionReasoning {
  applies: boolean
  reasoning: string
}

/** The reasoning model's own structured decision (reason.py's RecipeDecision). */
export interface RecipeDecisionReasoning {
  chosen_recipe_id: string
  ingredient_match_reasoning: DimensionReasoning
  freshness_reasoning: DimensionReasoning
  nutrition_reasoning: DimensionReasoning
  variety_reasoning: DimensionReasoning
  context_reasoning: DimensionReasoning
  taste_reasoning: DimensionReasoning
  overall_summary: string
}

/**
 * state["top_recommendation"] — either a cookable pick or an
 * explanation of why nothing was recommended. Shape varies by
 * `available`; every other field is genuinely optional depending on
 * which branch of reason.py produced it (a model choice, a fallback
 * override, or no candidates at all).
 */
export interface TopRecommendation {
  available: boolean
  recipe_id?: string | null
  explanation?: string
  overall_summary?: string
  reasoning?: RecipeDecisionReasoning
  invalid_model_choice?: boolean
  invalid_choice_reason?: string
  overrode_uncookable_choice?: boolean
  model_chosen_recipe_id?: string
}

/** One ingredient the frontend can show before a user confirms cooking. */
export interface MatchedIngredient {
  name: string
  quantity_display: string | null
  unit: string | null
}

export interface RankingEntry {
  recipe_id: string
  name: string | null
  match_score: number | null
  composite_score: number | null
  can_cook: boolean | null
}

export interface NodeTiming {
  node: string
  duration_ms: number
}

/** state["processing_trace"] — assembled by present.py, node 11. */
export interface ProcessingTraceEntry {
  node_timings: NodeTiming[]
  mcp_calls: Record<string, unknown>[]
  llm_calls: Record<string, unknown>[]
  ranking: RankingEntry[]
  errors: Record<string, unknown>[]
  retries: Record<string, unknown>[]
  relaxations: string[]
}

/**
 * The `result` field of GET /api/recommend/{session_id} once a run
 * completes — mealsight.api.routers.recommend._serialize_result's own
 * field set, flattening recipe_id onto the top level specifically so a
 * client has one obvious place to read it from before calling
 * POST /api/cook.
 */
export interface RecommendationResult {
  final_response?: string
  top_recommendation?: TopRecommendation
  scaled_recipe?: ScaledRecipe
  grocery_list?: GroceryList
  nutrition_info?: NutritionResult
  processing_trace?: ProcessingTraceEntry[]
  stream_messages?: string[]
  matched_ingredients?: MatchedIngredient[]
  /** Flattened from top_recommendation.recipe_id when available. */
  recipe_id?: string
}

export type RecommendationSessionStatus = 'pending' | 'running' | 'complete' | 'failed'

/** GET /api/recommend/{session_id} — the polling response. */
export interface RecommendationSessionResponse {
  session_id: string
  status: RecommendationSessionStatus
  result?: RecommendationResult
  error?: string
}
