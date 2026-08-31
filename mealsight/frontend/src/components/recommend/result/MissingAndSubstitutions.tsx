import type { Importance } from '@/types/matching'
import type { GroceryList } from '@/types/pantry'
import type { SubstitutionResult } from '@/types/recipe'

interface MissingIngredient {
  name: string
  importance: Importance
}

interface MissingAndSubstitutionsProps {
  missingIngredients: MissingIngredient[]
  substitutions: SubstitutionResult[] | undefined
  groceryList: GroceryList | undefined
}

const IMPORTANCE_LABEL: Record<Importance, string> = {
  critical: 'critical',
  important: 'important',
  optional: 'optional',
}

export function MissingAndSubstitutions({
  missingIngredients,
  substitutions,
  groceryList,
}: MissingAndSubstitutionsProps) {
  if (missingIngredients.length === 0 && !groceryList) return null

  return (
    <div className="flex flex-col gap-6">
      {missingIngredients.length > 0 && (
        <div>
          <h3 className="text-heading text-ink-900">Missing</h3>
          <ul className="mt-2 flex flex-col gap-1">
            {missingIngredients.map((item) => (
              <li key={item.name} className="flex items-center justify-between gap-3 py-1">
                <span className="text-body-lg text-ink-900">{item.name}</span>
                <span className="text-label text-steel-400">
                  {IMPORTANCE_LABEL[item.importance]}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {substitutions && substitutions.length > 0 && (
        <div>
          <h3 className="text-heading text-ink-900">Substitutions the engine found</h3>
          <div className="mt-2 flex flex-col gap-3">
            {substitutions.map((sub) => (
              <div key={sub.ingredient} className="rounded-sm bg-paper-1 p-3">
                <p className="text-body-lg font-medium text-ink-900">{sub.ingredient}</p>
                <ul className="mt-1 flex flex-col gap-1">
                  {sub.suggestions.map((suggestion) => (
                    <li key={suggestion.substitute} className="text-body text-ink-600">
                      {suggestion.substitute} — {suggestion.ratio}, {suggestion.flavor_impact}{' '}
                      flavor impact
                      {suggestion.notes ? ` (${suggestion.notes})` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {groceryList && (
        <div>
          <h3 className="text-heading text-ink-900">Grocery list</h3>
          <div className="mt-2 flex flex-col gap-4">
            {groceryList.sections.map((section) => (
              <div key={section.section}>
                <p className="text-label font-medium uppercase text-steel-400">{section.section}</p>
                <ul className="mt-1 flex flex-col gap-1">
                  {section.items.map((item) => (
                    <li key={item.name} className="py-1">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-body-lg text-ink-900">{item.name}</span>
                        <span className="text-label text-steel-400">
                          {IMPORTANCE_LABEL[item.importance]}
                        </span>
                      </div>
                      {/* Staple flag: the backend's own real verify_note
                          text, never a paraphrase invented here. */}
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
  )
}
