import { Stamp } from '@/components/primitives/Stamp'
import { Ticket } from '@/components/primitives/Ticket'
import type { RecommendationResult } from '@/types/recommendation'

interface NoCookableResultProps {
  result: RecommendationResult
}

/**
 * NEGATIVE state pattern — the common case with a sparse pantry, and
 * the state a reviewer is most likely to actually see. Reads as the
 * system being honest about what it considered, not as a failure: a
 * signal-negative Stamp, the backend's own real explanation (reason.py
 * already names the closest candidate, its match score, and what to
 * relax directly inside that explanation string — see reason.py's own
 * _no_cookable_explanation/_no_candidates_explanation, both of which
 * end with concrete relax-this-constraint advice), plus the grocery
 * list generate_output already built for that closest candidate so
 * there's always a concrete next action, never a dead end.
 */
export function NoCookableResult({ result }: NoCookableResultProps) {
  const explanation =
    result.top_recommendation?.explanation ??
    'Nothing in your pantry matched well enough this time.'

  return (
    <Ticket>
      <div className="flex flex-col gap-4">
        <Stamp signal="negative">no cookable match</Stamp>
        <p className="text-body-lg text-ink-900">{explanation}</p>

        {result.grocery_list && (
          <div>
            <h3 className="text-heading text-ink-900">What it would take</h3>
            <div className="mt-2 flex flex-col gap-4">
              {result.grocery_list.sections.map((section) => (
                <div key={section.section}>
                  <p className="text-label font-medium uppercase text-steel-400">
                    {section.section}
                  </p>
                  <ul className="mt-1 flex flex-col gap-1">
                    {section.items.map((item) => (
                      <li key={item.name} className="py-1">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-body-lg text-ink-900">{item.name}</span>
                          <span className="text-label text-steel-400">{item.importance}</span>
                        </div>
                        {item.is_staple && item.verify_note && (
                          <p className="mt-1 text-label text-signal-info">{item.verify_note}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Ticket>
  )
}
