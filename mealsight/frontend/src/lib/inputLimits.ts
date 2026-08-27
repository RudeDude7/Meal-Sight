// Mirrors mealsight/perception/validation.py and mealsight/config/
// settings.py directly — every number and format list here is read
// from those files, not guessed from what "seems reasonable" for a
// photo/audio/text upload. Kept in one place so a future backend
// change to any of these has exactly one frontend constant to update.

/** validation.py's own SUPPORTED_IMAGE_FORMATS, as browser MIME types. */
export const SUPPORTED_IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const

/** settings.py's own max_image_size_mb. */
export const MAX_IMAGE_SIZE_MB = 10

/** validation.py's own MIN_IMAGE_DIMENSION_PX — checked on both sides. */
export const MIN_IMAGE_DIMENSION_PX = 200

/**
 * validation.py's own SUPPORTED_AUDIO_FORMATS. WEBM is included since
 * that's what MediaRecorder produces in every browser except Safari
 * (which produces MP4/M4A) — both are accepted server-side.
 */
export const SUPPORTED_AUDIO_MIME_TYPES = [
  'audio/wav',
  'audio/x-wav',
  'audio/mpeg',
  'audio/mp4',
  'audio/x-m4a',
  'audio/webm',
] as const

/** validation.py's own MAX_AUDIO_FILE_SIZE_MB (Groq's own Whisper endpoint limit). */
export const MAX_AUDIO_SIZE_MB = 25

/** settings.py's own max_audio_duration_seconds. */
export const MAX_AUDIO_DURATION_SECONDS = 300

/** settings.py's own max_text_length. */
export const MAX_TEXT_LENGTH = 2000

export interface ValidationResult {
  valid: boolean
  message?: string
}

/**
 * Format + size checks only — validation.py also decodes the file to
 * check pixel dimensions, which isn't worth duplicating client-side
 * with a second image-decoding library; a too-small image still gets a
 * clear, specific error back from the server after upload rather than
 * silently failing, since that one check is comparatively rare to hit
 * and cheap to report after the fact.
 */
export function validateImageFile(file: File): ValidationResult {
  const sizeMb = file.size / (1024 * 1024)
  if (sizeMb > MAX_IMAGE_SIZE_MB) {
    return {
      valid: false,
      message: `Image is ${sizeMb.toFixed(1)}MB, over the ${MAX_IMAGE_SIZE_MB}MB limit.`,
    }
  }
  if (
    !SUPPORTED_IMAGE_MIME_TYPES.includes(file.type as (typeof SUPPORTED_IMAGE_MIME_TYPES)[number])
  ) {
    return {
      valid: false,
      message: 'Unsupported image format — use JPEG, PNG, or WEBP.',
    }
  }
  return { valid: true }
}

export function validateAudioFile(file: File): ValidationResult {
  const sizeMb = file.size / (1024 * 1024)
  if (sizeMb > MAX_AUDIO_SIZE_MB) {
    return {
      valid: false,
      message: `Audio is ${sizeMb.toFixed(1)}MB, over the ${MAX_AUDIO_SIZE_MB}MB limit.`,
    }
  }
  if (
    file.type &&
    !SUPPORTED_AUDIO_MIME_TYPES.includes(file.type as (typeof SUPPORTED_AUDIO_MIME_TYPES)[number])
  ) {
    return {
      valid: false,
      message: 'Unsupported audio format — use WAV, MP3, M4A, or WEBM.',
    }
  }
  return { valid: true }
}

export function validateText(text: string): ValidationResult {
  if (text.length > MAX_TEXT_LENGTH) {
    return {
      valid: false,
      message: `Text is ${text.length} characters, over the ${MAX_TEXT_LENGTH} character limit.`,
    }
  }
  return { valid: true }
}
