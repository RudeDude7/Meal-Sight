import type { WSMessage } from '@/types/websocket'

// mealsight/agent/graph.py's own NODE_ORDER, in order — the eleven
// steps every recommendation run passes through sequentially.
const PIPELINE_STEPS: { node: string; label: string }[] = [
  { node: 'validate_input', label: 'Validating input' },
  { node: 'perceive', label: 'Analyzing what you sent' },
  { node: 'merge', label: 'Combining what was found' },
  { node: 'update_pantry', label: 'Updating your pantry' },
  { node: 'get_context', label: 'Checking time of day & habits' },
  { node: 'search_recipes', label: 'Searching recipes' },
  { node: 'match_rank', label: 'Matching against your pantry' },
  { node: 'reason', label: 'Reasoning about the best fit' },
  { node: 'generate_output', label: 'Preparing your recommendation' },
  { node: 'record_outcome', label: 'Recording the outcome' },
  { node: 'present', label: 'Finishing up' },
]

type StepStatus = 'pending' | 'active' | 'done'

interface StepState {
  status: StepStatus
  durationMs: number | null
}

function deriveStepStates(messages: WSMessage[]): Map<string, StepState> {
  const states = new Map<string, StepState>()
  for (const message of messages) {
    if (message.type === 'node_start') {
      states.set(message.node, { status: 'active', durationMs: null })
    } else if (message.type === 'node_complete') {
      states.set(message.node, { status: 'done', durationMs: message.duration_ms })
    }
  }
  return states
}

interface PipelineProgressProps {
  messages: WSMessage[]
}

/**
 * node_start/node_complete drive an eleven-step progress view — the
 * agent graph's own real, sequential node order (mealsight/agent/
 * graph.py's NODE_ORDER), not an invented generic "step 1 of N".
 * Completed steps show their real duration straight from the
 * backend's own per-node timing wrapper, not an estimate.
 */
export function PipelineProgress({ messages }: PipelineProgressProps) {
  const stepStates = deriveStepStates(messages)

  return (
    <ol className="flex flex-col gap-1">
      {PIPELINE_STEPS.map(({ node, label }) => {
        const state = stepStates.get(node) ?? { status: 'pending' as const, durationMs: null }
        return (
          <li key={node} className="flex items-center gap-3 rounded-card px-2 py-1.5">
            <span
              className={[
                'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                state.status === 'done' && 'bg-brand-600 text-white',
                state.status === 'active' && 'bg-brand-100 text-brand-700',
                state.status === 'pending' && 'bg-surface-muted text-ink-faint',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-hidden="true"
            >
              {state.status === 'done' ? '✓' : ''}
            </span>
            <span
              className={[
                'text-body',
                state.status === 'done' && 'text-ink-muted',
                state.status === 'active' && 'font-medium text-ink',
                state.status === 'pending' && 'text-ink-faint',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {label}
              {state.status === 'active' && (
                <span className="ml-2 inline-flex gap-0.5 align-middle" aria-hidden="true">
                  <span className="h-1 w-1 animate-bounce rounded-full bg-brand-500 [animation-delay:-0.2s]" />
                  <span className="h-1 w-1 animate-bounce rounded-full bg-brand-500 [animation-delay:-0.1s]" />
                  <span className="h-1 w-1 animate-bounce rounded-full bg-brand-500" />
                </span>
              )}
            </span>
            {state.status === 'done' && state.durationMs !== null && (
              <span className="ml-auto text-caption text-ink-faint">
                {(state.durationMs / 1000).toFixed(1)}s
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}
