// Mirrors mealsight/api/messages.py field for field. Every message
// carries type/version/session_id/timestamp regardless of which of the
// eight kinds it is — WSMessage below is the discriminated union on
// `type`, matching the backend's own Annotated[Union[...],
// Field(discriminator="type")].

export const WS_PROTOCOL_VERSION = 1

interface BaseWSMessage {
  version: number
  session_id: string
  /** ISO 8601 timestamp string (pydantic's datetime, JSON-encoded). */
  timestamp: string
}

export interface NodeStartMessage extends BaseWSMessage {
  type: 'node_start'
  node: string
}

export interface NodeCompleteMessage extends BaseWSMessage {
  type: 'node_complete'
  node: string
  duration_ms: number
}

/** perceive's own per-modality progress event — used for all three modalities. */
export interface IngredientFoundMessage extends BaseWSMessage {
  type: 'ingredient_found'
  modality: 'vision' | 'audio' | 'text'
  message: string
}

export interface RecipeMatchMessage extends BaseWSMessage {
  type: 'recipe_match'
  recipe_id: string
  name: string | null
  match_score: number | null
  can_cook: boolean | null
}

export interface RecommendationMessage extends BaseWSMessage {
  type: 'recommendation'
  recipe_id: string | null
  summary: string
  available: boolean
}

/**
 * Defined for schema completeness — the backend's own reasoning node
 * does not emit this today (no provider in this project supports real
 * token streaming yet). Kept here so the union stays exhaustive with
 * the backend's own MESSAGE_CLASSES_BY_TYPE.
 */
export interface StreamTokenMessage extends BaseWSMessage {
  type: 'stream_token'
  token: string
  index: number | null
}

export interface ErrorMessage extends BaseWSMessage {
  type: 'error'
  code: string
  message: string
}

export interface CompleteMessage extends BaseWSMessage {
  type: 'complete'
  result: Record<string, unknown>
}

export type WSMessage =
  | NodeStartMessage
  | NodeCompleteMessage
  | IngredientFoundMessage
  | RecipeMatchMessage
  | RecommendationMessage
  | StreamTokenMessage
  | ErrorMessage
  | CompleteMessage

export type WSMessageType = WSMessage['type']
