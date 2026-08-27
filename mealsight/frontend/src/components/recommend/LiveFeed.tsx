import type {
  ErrorMessage,
  IngredientFoundMessage,
  RecipeMatchMessage,
  WSMessage,
} from '@/types/websocket'

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

interface LiveFeedProps {
  messages: WSMessage[]
}

/**
 * The centerpiece for making an 8-9 second vision call feel like
 * progress rather than a hang: each modality gets its own live status
 * line that updates in place every time a new ingredient_found message
 * arrives (a real start message, then a heartbeat roughly every 3s
 * while perceive's own real provider call is still in flight, then a
 * real completion) — visibly changing text, on the real cadence phase
 * 7.2 measured, not a generic spinner that looks identical whether
 * something is progressing or stuck.
 */
export function LiveFeed({ messages }: LiveFeedProps) {
  const modalityStatuses = latestPerModality(messages)
  const recipeMatches = dedupedRecipeMatches(messages)
  const errors = messages.filter((message): message is ErrorMessage => message.type === 'error')

  if (modalityStatuses.length === 0 && recipeMatches.length === 0 && errors.length === 0) {
    return null
  }

  return (
    <div className="flex flex-col gap-4">
      {modalityStatuses.length > 0 && (
        <div className="flex flex-col gap-2">
          {modalityStatuses.map((message) => (
            <div
              key={message.modality}
              className="flex items-center gap-2 rounded-card bg-surface-muted px-3 py-2"
            >
              <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-brand-500" />
              <span className="text-caption font-medium text-ink-muted">
                {MODALITY_LABEL[message.modality]}:
              </span>
              <span className="text-body text-ink">{message.message}</span>
            </div>
          ))}
        </div>
      )}

      {recipeMatches.length > 0 && (
        <div>
          <p className="text-caption font-medium text-ink-muted">Candidates considered</p>
          <ul className="mt-2 flex flex-col gap-1.5">
            {recipeMatches.map((match) => (
              <li
                key={match.recipe_id}
                className="flex items-center justify-between rounded-card border border-ink/10 bg-surface px-3 py-2"
              >
                <span className="text-body text-ink">{match.name ?? match.recipe_id}</span>
                <span className="flex items-center gap-2">
                  {match.match_score !== null && (
                    <span className="text-caption text-ink-faint">
                      {Math.round(match.match_score * 100)}% match
                    </span>
                  )}
                  {match.can_cook !== null && (
                    <span
                      className={[
                        'rounded-full px-2 py-0.5 text-[11px] font-medium',
                        match.can_cook
                          ? 'bg-brand-100 text-brand-700'
                          : 'bg-surface-muted text-ink-faint',
                      ].join(' ')}
                    >
                      {match.can_cook ? 'cookable' : 'missing items'}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {errors.length > 0 && (
        <div className="flex flex-col gap-2">
          {errors.map((err, index) => (
            <div
              key={`${err.timestamp}-${index}`}
              className="rounded-card border border-danger-500/20 bg-danger-50 px-3 py-2 text-body text-danger-600"
            >
              {err.message}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
