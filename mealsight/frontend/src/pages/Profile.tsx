import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import { getProfile, removeProfilePreference, updateProfile } from '@/api/profile'
import { PageError } from '@/components/common/PageError'
import { PageLoading } from '@/components/common/PageLoading'
import { EmptyState } from '@/components/primitives/EmptyState'
import { Button } from '@/components/primitives/Button'
import { Well } from '@/components/primitives/Well'
import { CuisinePreferenceBars } from '@/components/profile/CuisinePreferenceBars'
import { PreferenceListEditor } from '@/components/profile/PreferenceListEditor'
import type { BudgetSensitivity, CookingSkill, PreferenceType, UserProfile } from '@/types/profile'

const COOKING_SKILLS: CookingSkill[] = ['beginner', 'intermediate', 'advanced']
const BUDGET_SENSITIVITIES: BudgetSensitivity[] = ['budget', 'moderate', 'flexible']

export function Profile() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Local drafts for the scalar fields, seeded from the loaded profile
  // and only sent on an explicit Save — never auto-saved on every
  // keystroke/select change.
  const [householdSizeDraft, setHouseholdSizeDraft] = useState('')
  const [cookTimeDraft, setCookTimeDraft] = useState('')
  const [cookingSkillDraft, setCookingSkillDraft] = useState<CookingSkill>('intermediate')
  const [budgetDraft, setBudgetDraft] = useState<BudgetSensitivity>('moderate')
  const [proteinDraft, setProteinDraft] = useState('')
  const [savingField, setSavingField] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getProfile()
      setProfile(result)
      setHouseholdSizeDraft(String(result.household_size))
      setCookTimeDraft(String(result.preferred_cook_time_minutes))
      setCookingSkillDraft(result.cooking_skill)
      setBudgetDraft(result.budget_sensitivity)
      setProteinDraft(result.protein_preference ?? '')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load your profile.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function saveScalar(
    field: string,
    preferenceType: PreferenceType,
    value: unknown,
  ): Promise<void> {
    setSavingField(field)
    try {
      const updated = await updateProfile(preferenceType, value)
      setProfile(updated)
    } finally {
      setSavingField(null)
    }
  }

  async function handleAddListItem(
    preferenceType: 'dietary_restrictions' | 'disliked_ingredients',
    value: string,
  ): Promise<void> {
    const updated = await updateProfile(preferenceType, value)
    setProfile(updated)
  }

  async function handleRemoveListItem(
    preferenceType: 'dietary_restrictions' | 'disliked_ingredients',
    value: string,
  ): Promise<void> {
    const updated = await removeProfilePreference(preferenceType, value)
    setProfile(updated)
  }

  if (loading && profile === null) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">Profile</h1>
        <div className="mt-6">
          <PageLoading label="Loading your profile…" />
        </div>
      </section>
    )
  }

  if (error && profile === null) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">Profile</h1>
        <div className="mt-6">
          <PageError message={error} onRetry={() => void load()} />
        </div>
      </section>
    )
  }

  if (!profile) return null

  const cuisineEntries = Object.keys(profile.cuisine_preferences)

  return (
    <section className="rounded-sm bg-paper-raised p-8">
      <h1 className="text-title text-ink-900">Profile</h1>

      <div className="mt-6 flex flex-col gap-8">
        <PreferenceListEditor
          label="Dietary restrictions"
          hint="Rules recipes out entirely — never recommended against these."
          items={profile.dietary_restrictions}
          onAdd={(value) => handleAddListItem('dietary_restrictions', value)}
          onRemove={(value) => handleRemoveListItem('dietary_restrictions', value)}
        />

        <PreferenceListEditor
          label="Disliked ingredients"
          hint="Synonyms collapse to one canonical entry — typing a synonym of something already listed won't add a duplicate."
          items={profile.disliked_ingredients}
          onAdd={(value) => handleAddListItem('disliked_ingredients', value)}
          onRemove={(value) => handleRemoveListItem('disliked_ingredients', value)}
        />

        <div>
          <h3 className="text-heading text-ink-900">Cooking preferences</h3>
          <Well className="mt-3 flex flex-col gap-4 p-4">
            <div className="flex flex-wrap items-end gap-4">
              <label className="flex flex-col gap-1">
                <span className="text-label text-ink-600">Household size</span>
                <input
                  type="number"
                  min={1}
                  value={householdSizeDraft}
                  onChange={(event) => setHouseholdSizeDraft(event.target.value)}
                  className="w-16 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
                />
              </label>
              {householdSizeDraft !== String(profile.household_size) && (
                <Button
                  variant="secondary"
                  disabled={savingField === 'household_size'}
                  onClick={() =>
                    void saveScalar('household_size', 'household_size', Number(householdSizeDraft))
                  }
                >
                  Save
                </Button>
              )}

              <label className="flex flex-col gap-1">
                <span className="text-label text-ink-600">Preferred cook time (min)</span>
                <input
                  type="number"
                  min={1}
                  value={cookTimeDraft}
                  onChange={(event) => setCookTimeDraft(event.target.value)}
                  className="w-16 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
                />
              </label>
              {cookTimeDraft !== String(profile.preferred_cook_time_minutes) && (
                <Button
                  variant="secondary"
                  disabled={savingField === 'preferred_cook_time_minutes'}
                  onClick={() =>
                    void saveScalar(
                      'preferred_cook_time_minutes',
                      'preferred_cook_time_minutes',
                      Number(cookTimeDraft),
                    )
                  }
                >
                  Save
                </Button>
              )}
            </div>

            <div className="flex flex-wrap items-end gap-4">
              <label className="flex flex-col gap-1">
                <span className="text-label text-ink-600">Cooking skill</span>
                <select
                  value={cookingSkillDraft}
                  onChange={(event) => setCookingSkillDraft(event.target.value as CookingSkill)}
                  className="rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
                >
                  {COOKING_SKILLS.map((skill) => (
                    <option key={skill} value={skill}>
                      {skill}
                    </option>
                  ))}
                </select>
              </label>
              {cookingSkillDraft !== profile.cooking_skill && (
                <Button
                  variant="secondary"
                  disabled={savingField === 'cooking_skill'}
                  onClick={() =>
                    void saveScalar('cooking_skill', 'cooking_skill', cookingSkillDraft)
                  }
                >
                  Save
                </Button>
              )}

              <label className="flex flex-col gap-1">
                <span className="text-label text-ink-600">Budget sensitivity</span>
                <select
                  value={budgetDraft}
                  onChange={(event) => setBudgetDraft(event.target.value as BudgetSensitivity)}
                  className="rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
                >
                  {BUDGET_SENSITIVITIES.map((sensitivity) => (
                    <option key={sensitivity} value={sensitivity}>
                      {sensitivity}
                    </option>
                  ))}
                </select>
              </label>
              {budgetDraft !== profile.budget_sensitivity && (
                <Button
                  variant="secondary"
                  disabled={savingField === 'budget_sensitivity'}
                  onClick={() =>
                    void saveScalar('budget_sensitivity', 'budget_sensitivity', budgetDraft)
                  }
                >
                  Save
                </Button>
              )}
            </div>

            <div className="flex flex-wrap items-end gap-4">
              <label className="flex flex-col gap-1">
                <span className="text-label text-ink-600">Protein preference</span>
                <input
                  type="text"
                  value={proteinDraft}
                  onChange={(event) => setProteinDraft(event.target.value)}
                  placeholder="none set"
                  className="w-40 rounded-sm border border-ink-900/10 bg-paper-raised px-3 py-2 text-body-lg text-ink-900"
                />
              </label>
              {proteinDraft !== (profile.protein_preference ?? '') && (
                <Button
                  variant="secondary"
                  disabled={savingField === 'protein_preference'}
                  onClick={() =>
                    void saveScalar(
                      'protein_preference',
                      'protein_preference',
                      proteinDraft || null,
                    )
                  }
                >
                  Save
                </Button>
              )}
            </div>
          </Well>
        </div>

        <div>
          <h3 className="text-heading text-ink-900">Cuisine preferences</h3>
          <p className="mt-1 text-label text-steel-400">
            Read-only — computed from how you've rated meals you've cooked, never set directly.
          </p>
          {cuisineEntries.length === 0 ? (
            <div className="mt-3">
              <EmptyState
                illustration="spike"
                message="No cuisine preferences yet — rate the meals you cook and this builds up automatically."
              />
            </div>
          ) : (
            <div className="mt-3">
              <CuisinePreferenceBars
                scores={profile.cuisine_preferences}
                dataPoints={profile.cuisine_preference_data_points}
              />
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
