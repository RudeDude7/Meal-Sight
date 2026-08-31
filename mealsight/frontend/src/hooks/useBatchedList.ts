import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Coalesces rapidly-arriving items into one state update instead of
 * one per item. Built specifically for the loading view's own real
 * pacing (measured from real runs): ten recipe-match messages can
 * arrive within a single 74ms window near the end of a run. Without
 * batching, that's ten separate Strip mounts (and ten "printing in"
 * animations firing back to back) inside less than one animation
 * frame's worth of real time on a slower device — visible thrashing,
 * not the intended one-group arrival.
 *
 * Mechanism: push() enqueues into a ref (no re-render yet); the FIRST
 * push after an empty queue schedules one flush, `windowMs` later,
 * that commits every item queued during that window in a single
 * setState call. A slow trickle of messages (the normal, non-burst
 * case — one heartbeat every 3s) still each land within one
 * `windowMs` of their own arrival, which is imperceptible at the
 * windowMs this is actually used with (well under 100ms).
 */
export function useBatchedList<T>(windowMs: number): [T[], (item: T) => void] {
  const [items, setItems] = useState<T[]>([])
  const queueRef = useRef<T[]>([])
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const push = useCallback(
    (item: T) => {
      queueRef.current.push(item)
      if (timerRef.current !== null) return
      timerRef.current = setTimeout(() => {
        const batch = queueRef.current
        queueRef.current = []
        timerRef.current = null
        setItems((current) => [...current, ...batch])
      }, windowMs)
    },
    [windowMs],
  )

  return [items, push]
}
