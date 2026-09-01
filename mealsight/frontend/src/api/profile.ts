import { apiRequest } from '@/api/client'
import type { PreferenceType, UserProfile } from '@/types/profile'

/** GET /api/profile */
export async function getProfile(signal?: AbortSignal): Promise<UserProfile> {
  return apiRequest<UserProfile>('/api/profile', { signal })
}

/** PATCH /api/profile */
export async function updateProfile(
  preferenceType: PreferenceType,
  value: unknown,
  signal?: AbortSignal,
): Promise<UserProfile> {
  return apiRequest<UserProfile>('/api/profile', {
    method: 'PATCH',
    body: { preference_type: preferenceType, value },
    signal,
  })
}

/**
 * DELETE /api/profile — removes one entry from dietary_restrictions or
 * disliked_ingredients (the only two additive fields). A no-op, not an
 * error, when value isn't currently present.
 */
export async function removeProfilePreference(
  preferenceType: 'dietary_restrictions' | 'disliked_ingredients',
  value: string,
  signal?: AbortSignal,
): Promise<UserProfile> {
  return apiRequest<UserProfile>('/api/profile', {
    method: 'DELETE',
    body: { preference_type: preferenceType, value },
    signal,
  })
}
