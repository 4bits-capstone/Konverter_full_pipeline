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

it('gives the refreshed retry its own fresh timeout window instead of the original request\'s leftover budget', async () => {
  // The retry used to share the original AbortController/timer, so it
  // inherited whatever time was left rather than a full window — a retry
  // that's merely slow (not stuck) could be aborted almost immediately.
  // Simulate: the first request takes 900ms of a 1000ms budget before
  // 401ing, then the retry itself also takes 900ms. With a shared timer
  // only ~100ms would remain for the retry; with a fresh one per attempt
  // it has the full 1000ms and succeeds. The fetch mock has to honour the
  // AbortSignal itself (reject on abort) the same way the real fetch does,
  // or an abort silently has no effect on the outcome being asserted.
  vi.useFakeTimers()
  try {
    let resolveFirst: (value: unknown) => void
    let resolveSecond: (value: unknown) => void
    const firstResponse = new Promise((resolve) => {
      resolveFirst = resolve
    })
    const secondResponse = new Promise((resolve) => {
      resolveSecond = resolve
    })
    const withAbort = (response: Promise<unknown>, signal: AbortSignal) =>
      new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        response.then(resolve, reject)
      })
    const fetchMock = vi
      .fn()
      .mockImplementationOnce((_url: string, options: { signal: AbortSignal }) =>
        withAbort(firstResponse, options.signal),
      )
      .mockImplementationOnce((_url: string, options: { signal: AbortSignal }) =>
        withAbort(secondResponse, options.signal),
      )
    vi.stubGlobal('fetch', fetchMock)
    signOut.mockClear()
    refreshSession.mockClear()

    const requestPromise = apiRequest('/documents', { timeoutMs: 1000 })

    await vi.advanceTimersByTimeAsync(900)
    resolveFirst!({ ok: false, status: 401, json: async () => ({ detail: 'Not authenticated' }) })
    await vi.advanceTimersByTimeAsync(0)

    await vi.advanceTimersByTimeAsync(900)
    resolveSecond!({ ok: true, status: 200, json: async () => ({ documents: [] }) })

    await expect(requestPromise).resolves.toEqual({ documents: [] })
    expect(signOut).not.toHaveBeenCalled()
  } finally {
    vi.useRealTimers()
  }
})

it('loads report HTML with the same authentication and retry policy as JSON requests', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => '<html>Report</html>' })
  vi.stubGlobal('fetch', fetchMock)
  await expect(apiRequest('/documents/report/exports/accessible.html', { responseType: 'text' })).resolves.toBe('<html>Report</html>')
  expect(fetchMock.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer stale-token')
  expect(fetchMock.mock.calls[0][1]).not.toHaveProperty('responseType')
})

it('carries the same bearer token on a blob request as on a JSON request', async () => {
  // Real bug found live: /review-items/{id}/evidence.png and /source both
  // started requiring this same bearer auth, but the frontend was still
  // loading them as a plain <img src>/<a href> -- neither can ever carry
  // a custom header, so every evidence crop and "open original page" link
  // 401'd, always, for every document. The fix routes them through
  // apiRequest with responseType: 'blob' instead (see
  // src/lib/useAuthenticatedObjectUrl.ts) specifically so this same
  // header-attaching logic applies to them too.
  const evidencePng = new Blob(['png-bytes'], { type: 'image/png' })
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, blob: async () => evidencePng })
  vi.stubGlobal('fetch', fetchMock)
  await expect(
    apiRequest('/documents/doc-1/review-items/review-1/evidence.png', { responseType: 'blob' }),
  ).resolves.toBe(evidencePng)
  expect(fetchMock.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer stale-token')
})
