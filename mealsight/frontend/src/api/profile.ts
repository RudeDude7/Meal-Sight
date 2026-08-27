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
