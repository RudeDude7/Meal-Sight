import { useEffect, useRef, useState } from 'react'

import { websocketUrl } from '@/api/client'
import type { RecommendationResult } from '@/types/recommendation'
import type { WSMessage } from '@/types/websocket'

export type WebSocketConnectionStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

export interface UseWebSocketResult {
  messages: WSMessage[]
  status: WebSocketConnectionStatus
  /** Populated once a "complete" message arrives. */
  result: RecommendationResult | null
  /** Populated once an "error" message arrives, or the socket itself errors out. */
  error: string | null
}

const MAX_RECONNECT_ATTEMPTS = 5
const RECONNECT_BASE_DELAY_MS = 500

function isWSMessage(value: unknown): value is WSMessage {
  return (
    value !== null &&
    typeof value === 'object' &&
    typeof (value as Record<string, unknown>).type === 'string' &&
    typeof (value as Record<string, unknown>).session_id === 'string'
  )
}

/**
 * Connects to WS /ws/{session_id} and parses every message into the
 * discriminated WSMessage union. The backend (mealsight.api.streaming.
 * SessionStream) buffers every message for a session regardless of
 * when a client connects, and replays that whole buffer before
 * switching to live delivery — so this hook never has to guard against
 * "the recommendation already finished before I connected" itself;
 * connecting at all, promptly, is enough. It DOES have to guard against
 * a dropped connection losing whatever was in flight, hence the
 * reconnect-with-backoff below, and against leaking a socket or a
 * pending reconnect timer past unmount or a session_id change.
 */
export function useWebSocket(sessionId: string | null): UseWebSocketResult {
  const [messages, setMessages] = useState<WSMessage[]>([])
  const [status, setStatus] = useState<WebSocketConnectionStatus>('idle')
  const [result, setResult] = useState<RecommendationResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const terminalReceivedRef = useRef(false)
  const unmountedRef = useRef(false)

  useEffect(() => {
    if (!sessionId) {
      setStatus('idle')
      return
    }

    unmountedRef.current = false
    terminalReceivedRef.current = false
    reconnectAttemptRef.current = 0
    setMessages([])
    setResult(null)
    setError(null)

    function connect(): void {
      if (unmountedRef.current || !sessionId) return

      setStatus('connecting')
      const socket = new WebSocket(websocketUrl(`/ws/${sessionId}`))
      socketRef.current = socket

      // Each fresh connection replays the FULL buffered history from
      // the start (see this hook's own docstring), so messages are
      // reset per-connection rather than appended across reconnects —
      // appending would duplicate everything the previous connection
      // already received.
      setMessages([])

      socket.onopen = () => {
        if (unmountedRef.current) return
        reconnectAttemptRef.current = 0
        setStatus('open')
      }

      socket.onmessage = (event: MessageEvent<string>) => {
        if (unmountedRef.current) return
        let parsed: unknown
        try {
          parsed = JSON.parse(event.data)
        } catch {
          return
        }
        if (!isWSMessage(parsed)) return

        setMessages((prev) => [...prev, parsed])

        if (parsed.type === 'complete') {
          terminalReceivedRef.current = true
          setResult(parsed.result as RecommendationResult)
        } else if (parsed.type === 'error') {
          terminalReceivedRef.current = true
          setError(parsed.message)
        }
      }

      socket.onerror = () => {
        if (unmountedRef.current) return
        setStatus('error')
      }

      socket.onclose = () => {
        if (unmountedRef.current) return
        socketRef.current = null

        if (terminalReceivedRef.current) {
          setStatus('closed')
          return
        }

        if (reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
          setStatus('error')
          setError((current) => current ?? 'Lost connection to the recommendation stream.')
          return
        }

        const attempt = reconnectAttemptRef.current
        reconnectAttemptRef.current += 1
        const delay = RECONNECT_BASE_DELAY_MS * 2 ** attempt
        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      unmountedRef.current = true
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [sessionId])

  return { messages, status, result, error }
}
