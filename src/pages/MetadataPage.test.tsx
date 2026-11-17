import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DocumentBar } from '../components/DocumentBar'
import { KonverterProvider, useKonverter } from '../state/KonverterContext'
import { testDocument, testReviewItems } from '../test/fixtures'
import { metadataService, resetTestServices } from '../test/serviceMocks'
import { ApiError } from '../services/httpClient'
import type { MetadataFieldInfo } from '../types/konverter'
import { MetadataPage, metadataLoadErrorMessage, normaliseMetadataFields } from './MetadataPage'

vi.mock('../services', () => import('../test/serviceMocks'))
vi.mock('../services/httpClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/httpClient')>()
  return {
    ...actual,
    // The metadata evidence crop loads through an authenticated blob fetch
    // (see src/lib/useAuthenticatedObjectUrl.ts) rather than a plain
    // <img src>, so a real Blob stands in for the network here.
    apiRequest: vi.fn(async (path: string, init?: Parameters<typeof actual.apiRequest>[1]) =>
      init?.responseType === 'blob' ? new Blob([path], { type: 'image/png' }) : actual.apiRequest(path, init),
    ),
  }
})

function SeedCompletedDocument() {
  const { addDocuments, resolveAllReviews, setUploaded } = useKonverter()
  useEffect(() => {
    addDocuments([testDocument])
    setUploaded(true)
    void resolveAllReviews()
  }, [addDocuments, resolveAllReviews, setUploaded])
  return null
}

function renderMetadata(queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/metadata']}>
        <KonverterProvider>
          <SeedCompletedDocument />
          <DocumentBar />
          <MetadataPage />
        </KonverterProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function approveMetadataFields() {
  screen.getAllByRole('button', { name: /Approve/ }).forEach((button) => fireEvent.click(button))
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})
beforeEach(resetTestServices)

describe('MetadataPage', () => {
  it('normalises legacy and incomplete backend metadata fields', () => {
    const publishedDate = {
      flags: [{ code: 'partial_value', severity: 'review' as const, message: 'Only a year was found.' }],
      reviewNeeded: true,
      page: 2,
      evidence: 'Found on page 2.',
      source: 'Docling text · pages 1–8',
    }
    const normalised = normaliseMetadataFields({ published_date: publishedDate })

    expect(normalised.publishedDate).toEqual(publishedDate)
    expect(normalised.title.reviewNeeded).toBe(true)
    expect(normalised.citations.flags[0].code).toBe('unavailable')
  })

  it('shows rule-conflict and review flags in place of confidence scores', async () => {
    renderMetadata()

    expect(await screen.findByText('Rule conflict')).toBeInTheDocument()
    expect(screen.getAllByText('Needs review')).toHaveLength(2)
    expect(screen.queryByText('No issues')).not.toBeInTheDocument()
    expect(screen.getByText(/the copyright line \(page 2\) gives 2025-11/)).toBeInTheDocument()
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument()
  })

  it('shows where each value was found', async () => {
    renderMetadata()

    expect(await screen.findByRole('button', { name: /^Source: Page 1 · cataloguing details\./ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Source: Page 1 · report line\./ })).toBeInTheDocument()
  })

  it('shows values as plain text until the field is opened for editing', async () => {
    renderMetadata()

    const panel = (await screen.findByRole('heading', { name: 'Document metadata' })).closest('.panel') as HTMLElement
    expect(within(panel).getByText('Accessibility Standards Report')).toBeInTheDocument()
    expect(within(panel).getByText('18 June 2026')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Title/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open original page/ })).toBeInTheDocument()
    // Published date is the default active field, so the page sheet highlights it.
    const sheet = screen.getByRole('img', { name: /Source page \d+ with published date highlighted/ })
    expect(within(sheet).getByText('18 June 2026')).toHaveClass('hl')
    expect(within(sheet).getByText('Accessibility Standards Report')).not.toHaveClass('hl')

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0])

    expect(screen.getByRole('textbox', { name: /Title/ })).toHaveValue('Accessibility Standards Report')
    expect(screen.getByRole('button', { name: /Reset to rule suggestion/ })).toBeInTheDocument()
  })

  it('approves a field in place and reverts an edit on cancel', async () => {
    renderMetadata()
    await screen.findByRole('heading', { name: 'Document metadata' })

    // Published date (low), Jurisdiction and Citation (medium) all await sign-off.
    const pill = () => document.querySelector('.pill') as HTMLElement
    expect(pill()).toHaveTextContent('3 fields need review')
    fireEvent.click(screen.getAllByRole('button', { name: /Approve/ })[0])
    expect(pill()).toHaveTextContent('2 fields need review')

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    const title = screen.getByRole('textbox', { name: /Title/ })
    fireEvent.change(title, { target: { value: 'Something else entirely' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    const panel = screen.getByRole('heading', { name: 'Document metadata' }).closest('.panel') as HTMLElement
    expect(within(panel).getByText('Accessibility Standards Report')).toBeInTheDocument()
    expect(within(panel).queryByText('Something else entirely')).not.toBeInTheDocument()
  })

  it('allows another publisher and uses the revised final action', async () => {
    renderMetadata()
    await screen.findByRole('heading', { name: 'Document metadata' })

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[1])
    fireEvent.click(screen.getByRole('button', { name: /Add another/ }))
    expect(screen.getByRole('textbox', { name: 'Additional publisher 2' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Resolve 3 fields to continue/ })).toBeDisabled()
  })

  it('shows ticks for passed checks and empty boxes for incomplete checks', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderMetadata(queryClient)
    await screen.findByRole('heading', { name: 'Document metadata' })
    approveMetadataFields()
    fireEvent.click(screen.getByRole('button', { name: /Run final system checks/ }))
    const checks = within(await screen.findByRole('list', { name: 'Approval system checks' }))
    expect(checks.getAllByRole('img', { name: 'Passed' })).toHaveLength(4)
    for (const passed of checks.getAllByRole('img', { name: 'Passed' })) {
      expect(passed.querySelector('svg.lucide-check')).not.toBeNull()
    }

    // A blocking quote flag becoming unresolved while the dialog is open must not
    // display a warning icon or allow approval of incomplete work.
    await act(async () => {
      queryClient.setQueryData(['review-items', testDocument.id], testReviewItems.map((item, index) => ({
        ...item,
        type: index === 0 ? 'quote' : item.type,
        status: index === 0 ? 'pending' : 'accepted',
      })))
    })
    await waitFor(() => expect(checks.getAllByRole('img', { name: 'Blocked' })).toHaveLength(2))
    for (const unchecked of checks.getAllByRole('img', { name: 'Blocked' })) {
      expect(unchecked).toBeEmptyDOMElement()
    }
    expect(screen.getByRole('button', { name: 'Approve and open preview' })).toBeDisabled()
  })

  it('keeps the checklist and the resolved-count summary consistent when a non-blocking flag is still pending', async () => {
    // pendingCount only tracks *blocking* flags — approval doesn't require
    // a decision on non-blocking types (pictures/tables/footnotes) — so it
    // can read 0 while resolvedCount is still short of the total. Both
    // pieces of text in this same modal must agree, not contradict each
    // other (one saying "all flags have a decision", the other showing a
    // count short of the total).
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderMetadata(queryClient)
    await screen.findByRole('heading', { name: 'Document metadata' })
    approveMetadataFields()
    fireEvent.click(screen.getByRole('button', { name: /Run final system checks/ }))
    await screen.findByRole('list', { name: 'Approval system checks' })

    await act(async () => {
      queryClient.setQueryData(['review-items', testDocument.id], testReviewItems.map((item, index) => ({
        ...item,
        type: index === 0 ? 'table' : item.type,
        status: index === 0 ? 'pending' : 'accepted',
      })))
    })

    const summary = await screen.findByLabelText('Document approval summary')
    await waitFor(() => expect(within(summary).getByText(/resolved$/).textContent).not.toMatch(
      new RegExp(`^${testReviewItems.length}/${testReviewItems.length}`),
    ))
    const checklist = within(screen.getByRole('list', { name: 'Approval system checks' }))
    expect(checklist.getByText(/flags have a decision/)).not.toHaveTextContent(
      `All ${testReviewItems.length} flags have a decision`,
    )
  })

  it('updates the top bar after revised metadata is saved', async () => {
    renderMetadata()
    await screen.findByRole('heading', { name: 'Document metadata' })

    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    fireEvent.change(screen.getByRole('textbox', { name: /Title/ }), {
      target: { value: 'Revised Committals Report' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    approveMetadataFields()
    fireEvent.click(screen.getByRole('button', { name: /Run final system checks/ }))

    await waitFor(() => {
      const documentBar = document.querySelector('header')
      expect(documentBar).not.toBeNull()
      expect(within(documentBar as HTMLElement).getByText('Revised Committals Report')).toBeInTheDocument()
    })
    expect(screen.getByRole('dialog', { name: 'Approve Revised Committals Report?' })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Approval system checks' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve and open preview' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Approve and open preview' })).toHaveClass('btn-primary')
    expect(screen.getByRole('dialog')).toHaveAccessibleDescription(/Review the completed checks/)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('labels a field with no value as "Not found", not as a rule conflict', async () => {
    const original = await metadataService.get('doc')
    const missing: MetadataFieldInfo = {
      flags: [{ code: 'missing', severity: 'review', message: 'No value matched the metadata rules in pages 1–8.' }],
      reviewNeeded: true,
      page: 1,
      location: 'None found in pages 1–8',
      evidence: 'No value matched the configured metadata rules.',
      source: 'None found in pages 1–8',
    }
    vi.spyOn(metadataService, 'get').mockResolvedValue({
      ...original,
      metadata: { ...original.metadata, jurisdiction: '' },
      fields: { ...original.fields, jurisdiction: missing },
    })
    renderMetadata()

    expect(await screen.findByText('Not found')).toBeInTheDocument()
    expect(screen.getAllByText('Rule conflict')).toHaveLength(1)
    expect(screen.queryByText(/No metadata found automatically/)).not.toBeInTheDocument()
  })

  it('explains a scanned PDF once when the backend finds no readable text', async () => {
    const original = await metadataService.get('doc')
    const missing = normaliseMetadataFields({}).title
    const message = 'No readable text was found in pages 1–8 of this PDF. It may be a scanned or image-only document.'
    vi.spyOn(metadataService, 'get').mockResolvedValue({
      metadata: { title: '', publisher: '', publishedDate: '', jurisdiction: '', citations: '' },
      fields: Object.fromEntries(Object.keys(original.fields).map((key) => [key, {
        ...missing,
        flags: [{ code: 'missing', severity: 'review', message: 'No value matched.' }],
      }])) as typeof original.fields,
      notice: { code: 'no_text', message },
    })
    renderMetadata()

    const banner = (await screen.findByText(/No metadata found automatically/)).closest('.metadata-notice')
    expect(banner).toHaveTextContent(message)
    // An empty published date is also checked as required, so it reads "Value required".
    expect(screen.getAllByText('Not found')).toHaveLength(4)
    expect(screen.getByText('Value required')).toBeInTheDocument()
  })

  it('shows the failed save inline and keeps the reviewer on the page', async () => {
    vi.spyOn(metadataService, 'save').mockRejectedValue(new ApiError('The connection was interrupted.', 0))
    renderMetadata()
    await screen.findByRole('heading', { name: 'Document metadata' })
    approveMetadataFields()
    fireEvent.click(screen.getByRole('button', { name: /Run final system checks/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Metadata was not saved. The connection was interrupted.')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run final system checks/ })).toBeEnabled()
  })

  it('gives the reason a load failed and lets the reviewer retry', async () => {
    const original = await metadataService.get('doc')
    const get = vi.spyOn(metadataService, 'get')
      .mockRejectedValueOnce(new ApiError('Metadata is not ready yet', 409))
      .mockResolvedValue(original)
    renderMetadata()

    expect(await screen.findByRole('alert')).toHaveTextContent(/still processing/)
    expect(screen.getByRole('button', { name: 'Return to upload' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }))

    expect(await screen.findByRole('heading', { name: 'Document metadata' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('maps load failures to plain-language reasons', () => {
    expect(metadataLoadErrorMessage(new ApiError('Not found', 404))).toMatch(/could not be found/)
    expect(metadataLoadErrorMessage(new ApiError('Took too long', 408))).toBe('Took too long')
    expect(metadataLoadErrorMessage(new Error('boom'))).toMatch(/could not be loaded right now/)
  })
})
