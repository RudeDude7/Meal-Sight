import { useEffect, useId, useRef, useState } from 'react'

import { validateImageFile } from '@/lib/inputLimits'

interface PhotoInputProps {
  file: File | null
  onChange: (file: File | null) => void
  disabled?: boolean
}

/**
 * Drag-and-drop + a file picker + a dedicated camera-capture button for
 * mobile (a second <input type="file" capture="environment"> — the
 * standard way to force the device camera open directly rather than
 * the general photo picker, which the plain file input already covers
 * for "pick an existing photo"). Client-side validation runs before
 * ever calling onChange with a real file — an invalid file is reported
 * inline and never handed to the caller, so Home's own submit flow
 * never has to re-check format/size itself.
 */
export function PhotoInput({ file, onChange, disabled = false }: PhotoInputProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isDraggingOver, setIsDraggingOver] = useState(false)
  const pickerInputRef = useRef<HTMLInputElement>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)
  const inputId = useId()

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  function acceptFile(candidate: File): void {
    const result = validateImageFile(candidate)
    if (!result.valid) {
      setError(result.message ?? "That image can't be used.")
      onChange(null)
      return
    }
    setError(null)
    onChange(candidate)
  }

  function handleFileList(files: FileList | null): void {
    const candidate = files?.[0]
    if (candidate) acceptFile(candidate)
  }

  function handleRemove(): void {
    setError(null)
    onChange(null)
    if (pickerInputRef.current) pickerInputRef.current.value = ''
    if (cameraInputRef.current) cameraInputRef.current.value = ''
  }

  return (
    <div>
      <label htmlFor={inputId} className="text-subtitle text-ink">
        Photo
      </label>
      <p className="mt-1 text-caption text-ink-faint">JPEG, PNG, or WEBP, up to 10MB.</p>

      {previewUrl ? (
        <div className="mt-3 flex items-start gap-4">
          <img
            src={previewUrl}
            alt="Selected pantry or fridge photo"
            className="h-32 w-32 rounded-card border border-ink/10 object-cover"
          />
          <div className="flex flex-col gap-2">
            <span className="text-caption text-ink-muted">{file?.name}</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => pickerInputRef.current?.click()}
                disabled={disabled}
                className="rounded-card border border-ink/10 px-3 py-1.5 text-body text-ink hover:bg-surface-muted disabled:opacity-50"
              >
                Replace
              </button>
              <button
                type="button"
                onClick={handleRemove}
                disabled={disabled}
                className="rounded-card border border-danger-500/30 px-3 py-1.5 text-body text-danger-600 hover:bg-danger-50 disabled:opacity-50"
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div
          onDragOver={(event) => {
            event.preventDefault()
            setIsDraggingOver(true)
          }}
          onDragLeave={() => setIsDraggingOver(false)}
          onDrop={(event) => {
            event.preventDefault()
            setIsDraggingOver(false)
            handleFileList(event.dataTransfer.files)
          }}
          className={[
            'mt-3 flex flex-col items-center justify-center gap-3 rounded-card border-2 border-dashed p-6 text-center transition-colors',
            isDraggingOver ? 'border-brand-500 bg-brand-50' : 'border-ink/15 bg-surface-muted',
          ].join(' ')}
        >
          <p className="text-body text-ink-muted">Drag a photo here, or</p>
          <div className="flex flex-wrap justify-center gap-2">
            <button
              type="button"
              id={inputId}
              onClick={() => pickerInputRef.current?.click()}
              disabled={disabled}
              className="rounded-card bg-brand-600 px-4 py-2 text-body font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              Choose a photo
            </button>
            <button
              type="button"
              onClick={() => cameraInputRef.current?.click()}
              disabled={disabled}
              className="rounded-card border border-ink/10 px-4 py-2 text-body font-medium text-ink hover:bg-surface disabled:opacity-50"
            >
              Take a photo
            </button>
          </div>
        </div>
      )}

      {/* General picker — photo library on mobile, file browser on desktop. */}
      <input
        ref={pickerInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="sr-only"
        onChange={(event) => handleFileList(event.target.files)}
      />
      {/* capture="environment" forces the rear camera to open directly on mobile. */}
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        className="sr-only"
        onChange={(event) => handleFileList(event.target.files)}
      />

      {error && <p className="mt-2 text-caption text-danger-600">{error}</p>}
    </div>
  )
}
