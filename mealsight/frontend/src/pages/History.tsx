import { EmptyState } from '@/components/primitives/EmptyState'

export function History() {
  return (
    <section className="rounded-sm bg-paper-raised p-8">
      <h1 className="text-title text-ink-900">History</h1>
      <div className="mt-6">
        <EmptyState illustration="spike" message="No meals logged yet." />
      </div>
    </section>
  )
}
