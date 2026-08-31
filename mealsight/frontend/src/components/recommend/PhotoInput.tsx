import { useEffect, useId, useRef, useState } from 'react'

import { Button } from '@/components/primitives/Button'
import { Well } from '@/components/primitives/Well'
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
      <label htmlFor={inputId} className="text-heading text-ink-900">
        Photo
      </label>
      <p className="mt-1 text-label text-steel-400">JPEG, PNG, or WEBP, up to 10MB.</p>

      {previewUrl ? (
        <div className="mt-3 flex items-start gap-4">
          {/* 128px, not the 4-point scale's own 64px neighbor: a photo
              review thumbnail has to show enough real detail for the
              user to confirm it's the right shelf/fridge shot — halving
              it to 64px visibly degrades that, so this one stays. */}
          <img
            src={previewUrl}
            alt="Selected pantry or fridge photo"
            className="h-32 w-32 rounded-sm border border-ink-900/10 object-cover"
          />
          <div className="flex flex-col gap-2">
            <span className="text-label text-ink-600">{file?.name}</span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => pickerInputRef.current?.click()}
                disabled={disabled}
              >
                Replace
              </Button>
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
        </div>
      ) : (
        <Well
          className={[
            'mt-3 flex flex-col items-center justify-center gap-3 p-6 text-center transition-colors',
            isDraggingOver ? 'bg-signal-active/10' : '',
          ].join(' ')}
        >
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
            className="flex flex-col items-center gap-3"
          >
            <p className="text-body-lg text-ink-600">Drag a photo here, or</p>
            <div className="flex flex-wrap justify-center gap-2">
              <Button
                id={inputId}
                variant="primary"
                onClick={() => pickerInputRef.current?.click()}
                disabled={disabled}
              >
                Choose a photo
              </Button>
              <Button
                variant="secondary"
                onClick={() => cameraInputRef.current?.click()}
                disabled={disabled}
              >
                Take a photo
              </Button>
            </div>
          </div>
        </Well>
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

      {error && <p className="mt-2 text-label text-signal-negative">{error}</p>}
    </div>
  )
}
