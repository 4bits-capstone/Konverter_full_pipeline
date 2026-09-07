import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from './httpClient'
import { fastApiPublicationService } from './fastApi'

vi.mock('./httpClient', () => ({ apiRequest: vi.fn() }))

beforeEach(() => vi.mocked(apiRequest).mockReset())

describe('WordPress backend-only transport', () => {
  it('sends only a document ID to FastAPI, never WordPress credentials or HTML', async () => {
    const response = { pageId: 26036, status: 'draft' }
    vi.mocked(apiRequest).mockResolvedValue(response)
    await expect(fastApiPublicationService.publishToWordPress('document/with spaces'))
      .resolves.toEqual(response)
    expect(apiRequest).toHaveBeenCalledExactlyOnceWith(
      '/documents/document%2Fwith%20spaces/wordpress-publication',
      { method: 'POST', timeoutMs: 150_000 },
    )
  })

  it('checks saved publication metadata without issuing a publishing request', async () => {
    vi.mocked(apiRequest).mockResolvedValue(null)
    await expect(fastApiPublicationService.getWordPressPublication('test-document')).resolves.toBeNull()
    expect(apiRequest).toHaveBeenCalledExactlyOnceWith('/documents/test-document/wordpress-publication')
  })
})
