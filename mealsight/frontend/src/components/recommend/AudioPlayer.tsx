import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'

interface AudioPlayerProps {
  src: string
  /**
   * A known-correct duration in seconds, tracked independently of the
   * blob itself — MediaRecorder's own WebM output can leave the
   * container's Duration element unset, which the browser then
   * reports as Infinity rather than the real length (confirmed
   * directly in this project: reproducible for a multi-part/
   * timesliced recording, though not for the single-chunk recording
   * VoiceInput.tsx actually produces in every browser version tested
   * here — see that component's own comment for the full diagnosis).
   * Passing the tracked value means the displayed total and the seek
   * range never depend on that unreliable metadata at all. Pass null
   * when there's no independently-tracked value (an uploaded file) —
   * the browser's own reported duration is used instead, and only once
   * it's an actual finite number.
   */
  durationHintSeconds: number | null
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

/**
 * A minimal custom audio player, not the browser's native
 * `<audio controls>` — the native control renders its own total-
 * duration display straight from the media element's own (possibly
 * Infinity/NaN) `duration` property, with no way to override just that
 * one number from the outside. Building play/pause + a seek range +
 * time labels ourselves is what lets the tracked, always-correct
 * duration actually reach the screen.
 */
export function AudioPlayer({ src, durationHintSeconds }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [browserDuration, setBrowserDuration] = useState<number | null>(null)

  useEffect(() => {
    setCurrentTime(0)
    setIsPlaying(false)
    setBrowserDuration(null)
  }, [src])

  const knownDuration = durationHintSeconds ?? (browserDuration !== null ? browserDuration : null)

  function trustBrowserDuration(): void {
    const audio = audioRef.current
    // Only trusted when it's a real, finite number — this is exactly
    // the property that can come back as Infinity for a live-recorded
    // WebM blob with no Duration element, so it's never used blindly,
    // and a durationHintSeconds value (when present) always wins
    // regardless of what this reports.
    if (audio && Number.isFinite(audio.duration)) setBrowserDuration(audio.duration)
  }

  function handleTimeUpdate(): void {
    if (audioRef.current) setCurrentTime(audioRef.current.currentTime)
  }

  function togglePlay(): void {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) {
      void audio.play()
    } else {
      audio.pause()
    }
  }

  function handleSeek(event: ChangeEvent<HTMLInputElement>): void {
    const audio = audioRef.current
    if (!audio) return
    const value = Number(event.target.value)
    audio.currentTime = value
    setCurrentTime(value)
  }

  return (
    <div className="flex w-full items-center gap-3">
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onLoadedMetadata={trustBrowserDuration}
        onDurationChange={trustBrowserDuration}
        onTimeUpdate={handleTimeUpdate}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
        className="hidden"
      />
      <button
        type="button"
        onClick={togglePlay}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white hover:bg-brand-700"
        aria-label={isPlaying ? 'Pause' : 'Play'}
      >
        {isPlaying ? '❚❚' : '▶'}
      </button>
      <input
        type="range"
        min={0}
        max={knownDuration ?? 0}
        step={0.1}
        value={Math.min(currentTime, knownDuration ?? currentTime)}
        onChange={handleSeek}
        disabled={knownDuration === null}
        className="h-1.5 flex-1 accent-brand-600"
        aria-label="Seek"
      />
      <span className="w-20 shrink-0 text-caption tabular-nums text-ink-faint">
        {formatTime(currentTime)} / {knownDuration !== null ? formatTime(knownDuration) : '—:—'}
      </span>
    </div>
  )
}
