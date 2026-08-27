import { useEffect, useMemo, useState } from 'react'

import { postRecommend } from '@/api/recommend'
import { ApiError } from '@/api/client'
import { LiveFeed } from '@/components/recommend/LiveFeed'
import { PhotoInput } from '@/components/recommend/PhotoInput'
import { PipelineProgress } from '@/components/recommend/PipelineProgress'
import { TextInput } from '@/components/recommend/TextInput'
import { VoiceInput } from '@/components/recommend/VoiceInput'
import { useWebSocket } from '@/hooks/useWebSocket'
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

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {showInputs && (
        <section className="rounded-card bg-surface p-6 shadow-card">
          <h1 className="text-display text-ink">What's for dinner?</h1>
          <p className="mt-2 text-body text-ink-muted">
            Upload a photo of your pantry, record a voice memo, or describe what you're craving.
          </p>

          <div className="mt-6 flex flex-col gap-6">
            <PhotoInput file={photo} onChange={setPhoto} disabled={isBusy} />
            <VoiceInput file={audio} onChange={setAudio} disabled={isBusy} />
            <TextInput value={text} onChange={setText} disabled={isBusy} />
          </div>

          <div className="mt-6 flex flex-col gap-2">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="rounded-card bg-brand-600 px-5 py-3 text-body font-semibold text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-ink/15 disabled:text-ink-faint"
            >
              {appState === 'submitting' ? 'Starting…' : 'Get a recommendation'}
            </button>
            {blockedReason && appState === 'idle' && (
              <p className="text-caption text-ink-faint">{blockedReason}</p>
            )}
            {submitError && <p className="text-caption text-danger-600">{submitError}</p>}
          </div>
        </section>
      )}

      {showStream && (
        <section className="rounded-card bg-surface p-6 shadow-card">
          <div className="flex items-center justify-between">
            <h2 className="text-subtitle text-ink">
              {appState === 'complete'
                ? 'Recommendation ready'
                : appState === 'error'
                  ? 'Something went wrong'
                  : 'Working on it…'}
            </h2>
            {ws.status === 'connecting' && appState === 'streaming' && (
              <span className="text-caption text-warning-600">Reconnecting…</span>
            )}
          </div>

          <div className="mt-4">
            <PipelineProgress messages={ws.messages} />
          </div>

          <div className="mt-4">
            <LiveFeed messages={ws.messages} />
          </div>

          {appState === 'error' && ws.error && (
            <div className="mt-4 rounded-card border border-danger-500/20 bg-danger-50 px-3 py-2 text-body text-danger-600">
              {ws.error}
            </div>
          )}

          {appState === 'complete' && (
            <div className="mt-4 rounded-card border border-brand-500/20 bg-brand-50 px-3 py-3 text-body text-ink">
              {ws.result?.final_response ??
                'Done — the recommendation card lands in the next session.'}
            </div>
          )}

          {(appState === 'complete' || appState === 'error') && (
            <button
              type="button"
              onClick={handleStartNew}
              className="mt-6 rounded-card border border-ink/10 px-4 py-2 text-body font-medium text-ink hover:bg-surface-muted"
            >
              Start a new recommendation
            </button>
          )}
        </section>
      )}
    </div>
  )
}
