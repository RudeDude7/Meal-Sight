import { useEffect, useRef, useState } from 'react'

import { AudioPlayer } from '@/components/recommend/AudioPlayer'
import { Button } from '@/components/primitives/Button'
import { Well } from '@/components/primitives/Well'
import { MAX_AUDIO_DURATION_SECONDS, validateAudioFile } from '@/lib/inputLimits'

interface VoiceInputProps {
  file: File | null
  onChange: (file: File | null) => void
  disabled?: boolean
}

type RecorderState =
  'idle' | 'requesting-permission' | 'recording' | 'recorded' | 'permission-denied'

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

const mediaRecorderSupported =
  typeof window !== 'undefined' && typeof window.MediaRecorder !== 'undefined'

/**
 * Records via MediaRecorder when available; always offers a plain file
 * upload as a fallback, both for browsers with no MediaRecorder support
 * at all and for a user who'd rather upload an existing voice memo than
 * record a new one. A denied microphone permission gets the system's
 * own BLOCKED state pattern (plain-language reason, no Stamp — nothing
 * has "happened" to stamp, an action is simply unavailable) — never a
 * silent no-op where the recording button just doesn't work with
 * nothing said about why.
 */
export function VoiceInput({ file, onChange, disabled = false }: VoiceInputProps) {
  const [state, setState] = useState<RecorderState>('idle')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  // The duration to trust for playback — set from the SAME live timer
  // already shown while recording, never from the recorded blob's own
  // reported duration. See this component's own comment on
  // handleStop below for why the blob's reported duration can't be
  // trusted here. null for an uploaded (not self-recorded) file, since
  // there's nothing tracked to report for that case — AudioPlayer
  // falls back to the browser's own duration then.
  const [recordedDurationSeconds, setRecordedDurationSeconds] = useState<number | null>(null)
  // Read inside recorder.onstop via a ref, not the elapsedSeconds state
  // directly — onstop is a callback captured once when startRecording
  // runs, so it would otherwise close over whatever elapsedSeconds was
  // AT THAT TIME (0), not its later, final value.
  const elapsedSecondsRef = useRef(0)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      streamRef.current?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  function stopTimer(): void {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  function stopStream(): void {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }

  async function startRecording(): Promise<void> {
    setUploadError(null)
    setState('requesting-permission')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []

      const recorder = new MediaRecorder(stream)
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        const extension = blob.type.includes('mp4') ? 'm4a' : 'webm'
        // The tracked elapsed time, not blob.duration (there is no such
        // property on a Blob to even read) and not the eventual
        // <audio>'s own reported duration either — a MediaRecorder-
        // produced WebM has no finalized Duration element in its own
        // container header, and this project confirmed directly (a
        // real headless-Chrome repro, not just cited documentation)
        // that the browser can report that as Infinity for a resulting
        // blob — reproduced here for a multi-part/timesliced
        // recording specifically. Recording our own elapsed seconds
        // the whole time sidesteps the question entirely: it's never
        // wrong, because it was never derived from the container at all.
        setRecordedDurationSeconds(elapsedSecondsRef.current)
        onChange(new File([blob], `recording.${extension}`, { type: blob.type }))
        stopStream()
      }

      recorder.start()
      setState('recording')
      setElapsedSeconds(0)
      elapsedSecondsRef.current = 0
      setRecordedDurationSeconds(null)
      timerRef.current = setInterval(() => {
        setElapsedSeconds((prev) => {
          const next = prev + 1
          elapsedSecondsRef.current = next
          if (next >= MAX_AUDIO_DURATION_SECONDS) {
            // Enforce the backend's own duration cap client-side too —
            // stop automatically rather than let a user record past a
            // limit the upload will just fail on anyway.
            stopRecording()
          }
          return next
        })
      }, 1000)
    } catch {
      setState('permission-denied')
    }
  }

  function stopRecording(): void {
    stopTimer()
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    setState('recorded')
  }

  function handleRemove(): void {
    onChange(null)
    setState('idle')
    setElapsedSeconds(0)
    setRecordedDurationSeconds(null)
    setUploadError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function handleFallbackFile(files: FileList | null): void {
    const candidate = files?.[0]
    if (!candidate) return
    const result = validateAudioFile(candidate)
    if (!result.valid) {
      setUploadError(result.message ?? "That audio file can't be used.")
      return
    }
    setUploadError(null)
    onChange(candidate)
    // No independently-tracked duration for an uploaded file — this
    // wasn't recorded here, so there's no elapsed timer to have
    // measured it. AudioPlayer falls back to the browser's own
    // reported duration for this case, which is fine for an uploaded,
    // already-finalized audio file (unlike a live MediaRecorder blob).
    setRecordedDurationSeconds(null)
    setState('recorded')
  }

  return (
    <div>
      <label className="text-heading text-ink-900">Voice memo</label>
      <p className="mt-1 text-label text-steel-400">
        Up to {Math.floor(MAX_AUDIO_DURATION_SECONDS / 60)} minutes. WAV, MP3, M4A, or WEBM.
      </p>

      <Well className="mt-3 p-4">
        {state === 'idle' && (
          <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
            <Button
              variant="primary"
              onClick={startRecording}
              disabled={disabled || !mediaRecorderSupported}
            >
              {mediaRecorderSupported ? 'Start recording' : 'Recording unavailable in this browser'}
            </Button>
            <span className="text-label text-steel-400">or upload an audio file</span>
          </div>
        )}

        {state === 'requesting-permission' && (
          <p className="text-body-lg text-ink-600">Requesting microphone access…</p>
        )}

        {state === 'permission-denied' && (
          <div>
            <p className="text-body-lg text-signal-negative">
              Microphone access was denied, so recording isn't available right now.
            </p>
            <p className="mt-1 text-label text-ink-600">
              Allow microphone access in your browser's site settings and try again, or upload an
              audio file instead.
            </p>
          </div>
        )}

        {state === 'recording' && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 animate-pulse rounded-full bg-signal-negative" />
              <span className="text-body-lg font-medium text-ink-900">
                Recording… {formatElapsed(elapsedSeconds)}
              </span>
            </div>
            <Button variant="secondary" onClick={stopRecording}>
              Stop
            </Button>
          </div>
        )}

        {state === 'recorded' && previewUrl && (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <AudioPlayer src={previewUrl} durationHintSeconds={recordedDurationSeconds} />
            <div className="flex gap-2">
              <Button
                variant="ghost"
                onClick={handleRemove}
                disabled={disabled}
                className="text-signal-negative hover:text-signal-negative"
              >
                Remove
              </Button>
            </div>
          </div>
        )}

        {state !== 'recording' && (
          <div className="mt-3 border-t border-ink-900/10 pt-3">
            <p className="text-label font-medium text-ink-600">Upload an audio file instead</p>
            <Button
              variant="secondary"
              className="mt-2"
              onClick={() => fileInputRef.current?.click()}
              disabled={disabled}
            >
              Choose a file
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/webm"
              disabled={disabled}
              onChange={(event) => handleFallbackFile(event.target.files)}
              className="sr-only"
            />
          </div>
        )}

        {uploadError && <p className="mt-2 text-label text-signal-negative">{uploadError}</p>}
      </Well>
    </div>
  )
}
