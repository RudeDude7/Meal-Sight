import { EmptyState } from '@/components/primitives/EmptyState'

export function Pantry() {
  return (
    <section className="rounded-sm bg-paper-raised p-8">
      <h1 className="text-title text-ink-900">Pantry</h1>
      <div className="mt-6">
        <EmptyState
          illustration="fridge"
          message="Your pantry is empty. Add a photo of your fridge or shelves to get started."
        />
      </div>
    </section>
  )
}
