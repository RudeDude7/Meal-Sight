import { Stamp } from '@/components/primitives/Stamp'
import type { NutritionResult } from '@/types/recipe'

// Mirrors mealsight/recipe_engine/nutrition.py's own
// MIN_COVERAGE_PCT_FOR_TAGS (80.0) exactly — the same boundary the
// backend itself uses to decide whether coverage_note reads as "all
// ingredients" or "totals likely understate the real values", and
// whether dietary tags get suppressed at all.
const MIN_COVERAGE_PCT_FOR_TAGS = 80.0

interface NutritionPanelProps {
  nutrition: NutritionResult
}

/**
 * PARTIAL/CAVEAT state pattern: signal-info, a small Stamp, explicitly
 * never styled as an error or a warning — the product's own character
 * is refusing to present incomplete nutrition data as if it were
 * complete, not alarming anyone about it. Below MIN_COVERAGE_PCT_FOR_
 * TAGS this renders the Stamp plus the backend's own real coverage_note
 * text (never an invented caveat) stated plainly, same size as
 * everything else here — not small print.
 */
export function NutritionPanel({ nutrition }: NutritionPanelProps) {
  const isPartial = nutrition.coverage_pct <= MIN_COVERAGE_PCT_FOR_TAGS

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <h3 className="text-heading text-ink-900">Nutrition (per serving)</h3>
        {isPartial && <Stamp signal="info">partial nutrition data</Stamp>}
      </div>

      {isPartial && (
        <p className="text-body-lg text-signal-info">
          {nutrition.coverage_note} ({nutrition.coverage_pct}% of ingredients covered)
        </p>
      )}

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {(
          [
            ['Calories', `${nutrition.calories}`],
            ['Protein', `${nutrition.protein_g}g`],
            ['Carbs', `${nutrition.carbs_g}g`],
            ['Fat', `${nutrition.fat_g}g`],
            ['Fiber', `${nutrition.fiber_g}g`],
            ['Sodium', `${nutrition.sodium_mg}mg`],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="rounded-sm bg-paper-1 p-3">
            <dt className="text-label text-steel-400">{label}</dt>
            <dd className="mt-1 font-mono text-heading text-ink-900">{value}</dd>
          </div>
        ))}
      </dl>

      {!isPartial && <p className="text-label text-steel-400">{nutrition.coverage_note}</p>}

      {nutrition.tags.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {nutrition.tags.map((tag) => (
            <span key={tag} className="rounded-sm bg-paper-1 px-2 py-1 text-label text-ink-600">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
