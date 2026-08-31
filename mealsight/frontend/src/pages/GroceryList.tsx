import { EmptyState } from '@/components/primitives/EmptyState'

export function GroceryList() {
  return (
    <section className="rounded-sm bg-paper-raised p-8">
      <h1 className="text-title text-ink-900">Grocery List</h1>
      <div className="mt-6">
        <EmptyState illustration="list-pad" message="Nothing on your grocery list yet." />
      </div>
    </section>
  )
}
