import { Strip } from '@/components/primitives/Strip'
import type { IngredientFoundMessage, RecipeMatchMessage, WSMessage } from '@/types/websocket'

const MODALITY_LABEL: Record<IngredientFoundMessage['modality'], string> = {
  vision: 'Photo',
  audio: 'Voice memo',
  text: 'Description',
}

function latestPerModality(messages: WSMessage[]): IngredientFoundMessage[] {
  const latest = new Map<string, IngredientFoundMessage>()
  for (const message of messages) {
    if (message.type === 'ingredient_found') latest.set(message.modality, message)
  }
  return [...latest.values()]
}

function dedupedRecipeMatches(messages: WSMessage[]): RecipeMatchMessage[] {
  const byId = new Map<string, RecipeMatchMessage>()
  for (const message of messages) {
    if (message.type === 'recipe_match') byId.set(message.recipe_id, message)
  }
  return [...byId.values()]
}

function formatClockTime(isoTimestamp: string): string {
  const date = new Date(isoTimestamp)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('en-US', { hour12: false })
}

interface LiveFeedProps {
  messages: WSMessage[]
}

/**
 * The centerpiece for making an 8-9 second vision call feel like
 * progress rather than a hang: each modality gets its own live Strip
 * that updates in place every time a new ingredient_found message
 * arrives (a real start message, then a heartbeat roughly every 3s
 * while perceive's own real provider call is still in flight, then a
 * real completion), each printing in with its own real message
 * timestamp — the same Strip primitive the loading view already uses,
 * not a bespoke pulse-dot status line. Errors are deliberately NOT
 * shown here — Home already surfaces ws.error prominently on its own
 * (a signal-negative block, not a printed log line), so a stream error
 * appearing a second time as a Strip here would just be a duplicate.
 */
export function LiveFeed({ messages }: LiveFeedProps) {
  const modalityStatuses = latestPerModality(messages)
  const recipeMatches = dedupedRecipeMatches(messages)

  if (modalityStatuses.length === 0 && recipeMatches.length === 0) return null

  return (
    <div className="flex flex-col gap-4">
      {modalityStatuses.length > 0 && (
        <div>
          <p className="text-label font-medium text-ink-600">Reading your input</p>
          <div className="mt-1">
            {modalityStatuses.map((message) => (
              <Strip
                key={message.modality}
                timestamp={formatClockTime(message.timestamp)}
                message={`${MODALITY_LABEL[message.modality]}: ${message.message}`}
              />
            ))}
          </div>
        </div>
      )}

      {recipeMatches.length > 0 && (
        <div>
          <p className="text-label font-medium text-ink-600">Candidates considered</p>
          <div className="mt-1">
            {recipeMatches.map((match) => {
              const scoreText =
                match.match_score !== null ? `${Math.round(match.match_score * 100)}% match` : null
              const cookableText =
                match.can_cook !== null ? (match.can_cook ? 'cookable' : 'missing items') : null
              const detail = [scoreText, cookableText].filter(Boolean).join(', ')
              return (
                <Strip
                  key={match.recipe_id}
                  timestamp={formatClockTime(match.timestamp)}
                  message={`${match.name ?? match.recipe_id}${detail ? ` — ${detail}` : ''}`}
                />
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
