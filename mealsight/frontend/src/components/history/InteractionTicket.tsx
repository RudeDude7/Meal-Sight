import { RecipeIcon } from '@/components/primitives/RecipeIcon'
import { Stamp } from '@/components/primitives/Stamp'
import { Ticket } from '@/components/primitives/Ticket'
import { useRecipeIconCategory } from '@/lib/useRecipeIconCategory'
import type { InteractionRecord } from '@/types/profile'

interface InteractionTicketProps {
  interaction: InteractionRecord
}

/**
 * Every recommendation REQUEST, cooked or not — text only (voice_
 * transcript is already-transcribed text, ingredients_summary a short
 * description of what a photo yielded, never raw media). A run that
 * recommended nothing is the common case, not a failure: it gets the
 * same signal-negative-Stamp-plus-plain-explanation vocabulary the
 * recommendation result view itself uses for the identical situation,
 * without inventing a "start a new recommendation" action here — this
 * is a historical record, not a live moment with something to retry.
 */
export function InteractionTicket({ interaction }: InteractionTicketProps) {
  const iconCategory = useRecipeIconCategory(interaction.recommended_recipe_id)
  const recommended = interaction.recommended_recipe_id !== null

  return (
    <Ticket padding="compact">
      <div className="flex items-start gap-4">
        {recommended && iconCategory && <RecipeIcon category={iconCategory} />}
        <div className="flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {recommended ? (
                <Stamp signal="positive">recommended</Stamp>
              ) : (
                <Stamp signal="negative">no match</Stamp>
              )}
              {interaction.modalities.map((modality) => (
                <span key={modality} className="text-label capitalize text-steel-400">
                  {modality}
                </span>
              ))}
            </div>
            <span className="text-label text-steel-400">
              {new Date(interaction.created_at).toLocaleString()}
            </span>
          </div>

          {interaction.text_input && (
            <p className="mt-2 text-body-lg text-ink-900">"{interaction.text_input}"</p>
          )}
          {interaction.voice_transcript && (
            <p className="mt-2 text-body-lg text-ink-900">"{interaction.voice_transcript}"</p>
          )}
          {interaction.ingredients_summary && (
            <p className="mt-1 text-label text-ink-600">{interaction.ingredients_summary}</p>
          )}

          {recommended ? (
            <p className="mt-2 text-body-lg font-medium text-ink-900">
              {interaction.recommended_recipe_name}
            </p>
          ) : (
            interaction.final_response && (
              <p className="mt-2 text-body-lg text-ink-900">{interaction.final_response}</p>
            )
          )}
        </div>
      </div>
    </Ticket>
  )
}
