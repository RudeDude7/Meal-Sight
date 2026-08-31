import { useEffect, useMemo, useState } from 'react'

import { postRecommend } from '@/api/recommend'
import { ApiError } from '@/api/client'
import { Button } from '@/components/primitives/Button'
import { LiveFeed } from '@/components/recommend/LiveFeed'
import { PhotoInput } from '@/components/recommend/PhotoInput'
import { PipelineProgress } from '@/components/recommend/PipelineProgress'
import { RecommendationResultView } from '@/components/recommend/result/RecommendationResultView'
import { TextInput } from '@/components/recommend/TextInput'
import { VoiceInput } from '@/components/recommend/VoiceInput'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useActiveSession } from '@/lib/activeSessionContext'
import { MAX_TEXT_LENGTH } from '@/lib/inputLimits'

type AppState = 'idle' | 'submitting' | 'streaming' | 'complete' | 'error'

function disabledReason(photo: File | null, audio: File | null, text: string): string | null {
  if (photo || audio) return null
  const trimmed = text.trim()
  if (trimmed.length === 0) {
    return 'Add a photo, voice memo, or description to get a recommendation.'
  }
  if (text.length > MAX_TEXT_LENGTH) {
    return `Your description is over the ${MAX_TEXT_LENGTH} character limit — trim it, or add a photo or voice memo instead.`
  }
  return null
}

export function Home() {
  const [photo, setPhoto] = useState<File | null>(null)
  const [audio, setAudio] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [appState, setAppState] = useState<AppState>('idle')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const ws = useWebSocket(appState === 'idle' ? null : sessionId)
  const { setTraceId } = useActiveSession()

  // The masthead's own ticket number (NavShell) shows this real
  // session_id — the same id the backend uses as the agent run's own
  // trace_id — for exactly as long as a run is actually in flight,
  // and reverts to its idle placeholder the moment it isn't (complete,
  // errored, or a fresh "start new").
  useEffect(() => {
    setTraceId(appState === 'streaming' ? sessionId : null)
    return () => setTraceId(null)
  }, [appState, sessionId, setTraceId])

  const blockedReason = useMemo(() => disabledReason(photo, audio, text), [photo, audio, text])
  const isBusy = appState === 'submitting' || appState === 'streaming'
  const canSubmit = blockedReason === null && !isBusy

  // Session-level transitions driven by the WebSocket's own terminal
  // messages: a "complete" message means the run finished (ws.result
  // populated), an "error" message (or the socket giving up on
  // reconnecting) means it didn't — either way that's a real state
  // transition, not something to derive inline during render.
  useEffect(() => {
    if (appState !== 'streaming') return
    if (ws.result) setAppState('complete')
    else if (ws.error) setAppState('error')
  }, [appState, ws.result, ws.error])

  async function handleSubmit(): Promise<void> {
    setSubmitError(null)
    setAppState('submitting')
    try {
      const accepted = await postRecommend({
        image: photo ?? undefined,
        audio: audio ?? undefined,
        text,
      })
      setSessionId(accepted.session_id)
      setAppState('streaming')
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : 'Could not start a recommendation.')
      setAppState('idle')
    }
  }

  function handleStartNew(): void {
    setPhoto(null)
    setAudio(null)
    setText('')
    setSessionId(null)
    setSubmitError(null)
    setAppState('idle')
  }

  const showInputs = appState === 'idle' || appState === 'submitting'
  const showStream = appState === 'streaming' || appState === 'complete' || appState === 'error'
  // top_recommendation.available is the backend's own real signal for
  // "considered everything, nothing was cookable" (reason.py) — never
  // inferred from final_response being empty or absent.
  const recommendationAvailable = ws.result?.top_recommendation?.available

  // showInputs and showStream are mutually exclusive by construction
  // (idle/submitting vs. streaming/complete/error never overlap) — a
  // two-column grid here always rendered exactly one child, permanently
  // leaving the second column empty and full-height on anything wider
  // than a phone, unlike every other page's single full-width section
  // in the shared 960px column. A plain stack matches them.
  return (
    <div className="flex flex-col gap-6">
      {showInputs && (
        <section className="rounded-sm bg-paper-raised p-6">
          <h1 className="text-title text-ink-900">What's for dinner?</h1>
          <p className="mt-2 text-body-lg text-ink-600">
            Upload a photo of your pantry, record a voice memo, or describe what you're craving.
          </p>

          <div className="mt-6 flex flex-col gap-6">
            <PhotoInput file={photo} onChange={setPhoto} disabled={isBusy} />
            <VoiceInput file={audio} onChange={setAudio} disabled={isBusy} />
            <TextInput value={text} onChange={setText} disabled={isBusy} />
          </div>

          <div className="mt-6 flex flex-col gap-2">
            <Button variant="primary" onClick={handleSubmit} disabled={!canSubmit}>
              {appState === 'submitting' ? 'Starting…' : 'Get a recommendation'}
            </Button>
            {/* BLOCKED state pattern: a plain-language reason, no Stamp —
                nothing has happened yet to stamp, an action is simply
                unavailable until the reason is addressed. */}
            {blockedReason && appState === 'idle' && (
              <p className="text-label text-steel-400">{blockedReason}</p>
            )}
            {submitError && <p className="text-label text-signal-negative">{submitError}</p>}
          </div>
        </section>
      )}

      {showStream && (
        <section className="rounded-sm bg-paper-raised p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-heading text-ink-900">
              {appState === 'complete'
                ? recommendationAvailable === false
                  ? 'No match this time'
                  : 'Recommendation ready'
                : appState === 'error'
                  ? 'Something went wrong'
                  : 'Working on it…'}
            </h2>
            {ws.status === 'connecting' && appState === 'streaming' && (
              <span className="text-label text-signal-active">Reconnecting…</span>
            )}
          </div>

          <div className="mt-4">
            <PipelineProgress messages={ws.messages} />
          </div>

          <div className="mt-4">
            <LiveFeed messages={ws.messages} />
          </div>

          {appState === 'error' && ws.error && (
            <div className="mt-4 rounded-sm border border-signal-negative/20 bg-signal-negative/10 px-3 py-2 text-body-lg text-signal-negative">
              {ws.error}
            </div>
          )}

          {appState === 'complete' && ws.result && (
            <div className="mt-4">
              <RecommendationResultView result={ws.result} />
            </div>
          )}

          {(appState === 'complete' || appState === 'error') && (
            <Button variant="secondary" onClick={handleStartNew} className="mt-6">
              Start a new recommendation
            </Button>
          )}
        </section>
      )}
    </div>
  )
}
