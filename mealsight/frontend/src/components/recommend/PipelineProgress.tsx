import { Strip } from '@/components/primitives/Strip'
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

type StepStatus = 'active' | 'done'

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

function formatDuration(durationMs: number): string {
  if (durationMs < 1000) {
    return `${durationMs < 10 ? durationMs.toFixed(2) : Math.round(durationMs)}ms`
  }
  return `${(durationMs / 1000).toFixed(1)}s`
}

interface PipelineProgressProps {
  messages: WSMessage[]
}

/**
 * node_start/node_complete drive an eleven-step Strip sequence — the
 * agent graph's own real, sequential node order (mealsight/agent/
 * graph.py's NODE_ORDER), not an invented generic "step 1 of N". A step
 * that hasn't started yet isn't rendered at all — the literal ticket-
 * rail metaphor: a printer doesn't pre-print a line it doesn't have yet,
 * it prints one as each step genuinely begins (Strip's own print-in
 * animation). Completed steps show their real duration straight from
 * the backend's own per-node timing wrapper, in mono, right where the
 * old bounce-dots used to be — that data is genuine and worth keeping,
 * the animated dots were not.
 */
export function PipelineProgress({ messages }: PipelineProgressProps) {
  const stepStates = deriveStepStates(messages)
  const started = PIPELINE_STEPS.filter(({ node }) => stepStates.has(node))

  if (started.length === 0) return null

  return (
    <div className="flex flex-col">
      {started.map(({ node, label }) => {
        const state = stepStates.get(node)
        if (!state) return null
        return (
          <Strip
            key={node}
            timestamp={
              state.status === 'done' && state.durationMs !== null
                ? formatDuration(state.durationMs)
                : '…'
            }
            message={label}
          />
        )
      })}
    </div>
  )
}
