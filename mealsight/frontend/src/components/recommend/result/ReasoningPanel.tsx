import type { RecipeDecisionReasoning } from '@/types/recommendation'

const DIMENSION_LABELS: Record<
  keyof Omit<RecipeDecisionReasoning, 'overall_summary' | 'chosen_recipe_id'>,
  string
> = {
  ingredient_match_reasoning: 'Ingredients',
  freshness_reasoning: 'Freshness',
  nutrition_reasoning: 'Nutrition',
  variety_reasoning: 'Variety',
  context_reasoning: 'Context',
  taste_reasoning: 'Taste',
}

interface ReasoningPanelProps {
  reasoning: RecipeDecisionReasoning | undefined
  overallSummary: string | undefined
}

/**
 * The agent's own six-dimension explanation — mealsight/agent/nodes/
 * reason.py's own RecipeDecision, read back field for field. A
 * dimension the model marked NOT applicable renders anyway, dimmed
 * rather than dropped: reason.py's own system prompt requires the model
 * to "say so plainly instead of inventing a rationale" for exactly this
 * case, and dropping the row would throw away that honesty rather than
 * display it. reasoning itself is absent on the fallback paths (an
 * invalid model choice, an unexpected reasoning failure) — those show
 * only the plain overall_summary, never a fabricated six-row breakdown
 * for a decision that never actually went through per-dimension
 * reasoning.
 */
export function ReasoningPanel({ reasoning, overallSummary }: ReasoningPanelProps) {
  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-heading text-ink-900">Why this recipe</h3>

      {overallSummary && <p className="text-body-lg text-ink-900">{overallSummary}</p>}

      {reasoning && (
        <dl className="flex flex-col gap-4">
          {(Object.keys(DIMENSION_LABELS) as (keyof typeof DIMENSION_LABELS)[]).map((key) => {
            const dimension = reasoning[key]
            return (
              <div key={key} className="border-l-[3px] border-ink-900/10 pl-4">
                <dt
                  className={[
                    'text-label font-medium',
                    dimension.applies ? 'text-ink-900' : 'text-steel-400',
                  ].join(' ')}
                >
                  {DIMENSION_LABELS[key]}
                  {!dimension.applies && ' — not a factor this time'}
                </dt>
                <dd
                  className={[
                    'mt-1 text-body-lg',
                    dimension.applies ? 'text-ink-900' : 'text-ink-600',
                  ].join(' ')}
                >
                  {dimension.reasoning}
                </dd>
              </div>
            )
          })}
        </dl>
      )}
    </div>
  )
}
