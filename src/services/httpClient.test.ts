import { describe, expect, it, vi } from 'vitest'

vi.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: 'stale-token' } } }),
      signOut: vi.fn().mockResolvedValue({ error: null }),
    },
  },
}))

import { supabase } from '../lib/supabaseClient'
import { apiRequest, ApiError } from './httpClient'

const signOut = supabase.auth.signOut as ReturnType<typeof vi.fn>

describe('apiRequest', () => {
  it('signs the user out and surfaces a session-expired message on 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Not authenticated' }),
      }),
    )

    await expect(apiRequest('/documents')).rejects.toMatchObject({
      message: 'Your session has expired. Please sign in again.',
      status: 401,
    } satisfies Partial<ApiError>)

    expect(signOut).toHaveBeenCalledTimes(1)
  })
})
