import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import { getGroceryList } from '@/api/grocery'
import { PageError } from '@/components/common/PageError'
import { PageLoading } from '@/components/common/PageLoading'
import { EmptyState } from '@/components/primitives/EmptyState'
import { Ticket } from '@/components/primitives/Ticket'
import { GroceryItemRow } from '@/components/grocery/GroceryItemRow'
import type { GroceryList as GroceryListType } from '@/types/pantry'

function itemKey(section: string, name: string): string {
  return `${section}::${name}`
}

export function GroceryList() {
  const [list, setList] = useState<GroceryListType | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // Checked state is NOT persisted anywhere — pantry_manager has no
  // check/toggle tool at all (verified by reading every @mcp.tool in
  // mealsight/mcp_servers/pantry_manager/server.py: update_pantry, get_
  // pantry, remove_items, flag_expiring, create_grocery_list, get_
  // grocery_list — six tools, none of them a checked-state write), and
  // no REST route exists for it either. Per this task's own explicit
  // instruction, this stays client-only rather than inventing an
  // endpoint — it resets on reload, which IS the honest behavior for
  // data that genuinely isn't saved anywhere.
  const [checkedKeys, setCheckedKeys] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setNotFound(false)
    try {
      const result = await getGroceryList()
      setList(result)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true)
      } else {
        setError(err instanceof ApiError ? err.message : 'Could not load your grocery list.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  function toggleChecked(key: string): void {
    setCheckedKeys((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (loading && list === null && !notFound) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">Grocery List</h1>
        <div className="mt-6">
          <PageLoading label="Loading your grocery list…" />
        </div>
      </section>
    )
  }

  if (error) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">Grocery List</h1>
        <div className="mt-6">
          <PageError message={error} onRetry={() => void load()} />
        </div>
      </section>
    )
  }

  if (notFound || !list || list.sections.length === 0) {
    return (
      <section className="rounded-sm bg-paper-raised p-8">
        <h1 className="text-title text-ink-900">Grocery List</h1>
        <div className="mt-6">
          <EmptyState
            illustration="list-pad"
            message="Nothing on your grocery list yet — a list is generated automatically when a recommendation finds ingredients you're missing."
          />
        </div>
      </section>
    )
  }

  return (
    <section className="rounded-sm bg-paper-raised p-8">
      <h1 className="text-title text-ink-900">Grocery List</h1>

      <div className="mt-6 flex flex-col gap-6">
        {list.sections.map((section) => (
          <Ticket key={section.section}>
            <h2 className="text-heading capitalize text-ink-900">{section.section}</h2>
            <ul className="mt-2 flex flex-col divide-y divide-ink-900/10">
              {section.items.map((item) => (
                <GroceryItemRow
                  key={item.name}
                  item={item}
                  checked={checkedKeys.has(itemKey(section.section, item.name))}
                  onToggle={() => toggleChecked(itemKey(section.section, item.name))}
                />
              ))}
            </ul>
          </Ticket>
        ))}
      </div>
    </section>
  )
}
