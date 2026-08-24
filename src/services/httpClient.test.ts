import { describe, expect, it, vi } from 'vitest'

vi.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: 'stale-token' } } }),
      refreshSession: vi.fn().mockResolvedValue({ error: null }),
      signOut: vi.fn().mockResolvedValue({ error: null }),
    },
  },
}))

import { supabase } from '../lib/supabaseClient'
import { apiRequest, ApiError } from './httpClient'

const signOut = supabase.auth.signOut as ReturnType<typeof vi.fn>
const refreshSession = supabase.auth.refreshSession as ReturnType<typeof vi.fn>

describe('apiRequest', () => {
  it('signs the user out and surfaces a session-expired message when 401 persists after a refreshed retry', async () => {
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

    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(signOut).toHaveBeenCalledTimes(1)
  })

  it('retries once with a refreshed token and recovers from a transient 401 without signing out', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Not authenticated' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ documents: [] }),
      })
    vi.stubGlobal('fetch', fetchMock)
    signOut.mockClear()
    refreshSession.mockClear()

    await expect(apiRequest('/documents')).resolves.toEqual({ documents: [] })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(signOut).not.toHaveBeenCalled()
  })
})
