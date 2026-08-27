import { apiRequest, apiRequestMultipart } from '@/api/client'
import type { RecommendationAccepted, RecommendationSessionResponse } from '@/types/recommendation'

export interface RecommendInput {
  image?: File
  audio?: File
  text?: string
}

/** POST /api/recommend — multipart upload, returns 202 immediately with a session to poll or stream. */
export async function postRecommend(
  input: RecommendInput,
  signal?: AbortSignal,
): Promise<RecommendationAccepted> {
  const formData = new FormData()
  if (input.image) formData.set('image', input.image)
  if (input.audio) formData.set('audio', input.audio)
  if (input.text) formData.set('text', input.text)
  return apiRequestMultipart<RecommendationAccepted>('/api/recommend', formData, signal)
}

/** GET /api/recommend/{session_id} — poll for a session's current status/result. */
export async function getRecommendationSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<RecommendationSessionResponse> {
  return apiRequest<RecommendationSessionResponse>(
    `/api/recommend/${encodeURIComponent(sessionId)}`,
    {
      signal,
    },
  )
}
