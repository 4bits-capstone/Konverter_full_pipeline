import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DocumentBar } from '../components/DocumentBar'
import { KonverterProvider, useKonverter } from '../state/KonverterContext'
import { testDocument } from '../test/fixtures'
import { resetTestServices } from '../test/serviceMocks'
import { MetadataPage, normaliseMetadataFields } from './MetadataPage'

vi.mock('../services', () => import('../test/serviceMocks'))

function SeedCompletedDocument() {
  const { addDocuments, resolveAllReviews, setUploaded } = useKonverter()
  useEffect(() => {
    addDocuments([testDocument])
    setUploaded(true)
    void resolveAllReviews()
  }, [addDocuments, resolveAllReviews, setUploaded])
  return null
}

function renderMetadata() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
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

afterEach(cleanup)
beforeEach(resetTestServices)

describe('MetadataPage', () => {
  it('normalises legacy and incomplete backend confidence fields', () => {
    const publishedDate = {
      band: 'med' as const,
      score: 0.74,
      page: 2,
      evidence: 'Found on page 2.',
      source: 'Docling text · pages 1–8',
    }
    const normalised = normaliseMetadataFields({ published_date: publishedDate })

    expect(normalised.publishedDate).toEqual(publishedDate)
    expect(normalised.title.band).toBe('low')
    expect(normalised.citations.band).toBe('low')
  })

  it('shows values as plain text until the field is opened for editing', async () => {
    renderMetadata()

    const panel = (await screen.findByRole('heading', { name: 'Document metadata' })).closest('.panel') as HTMLElement
    expect(within(panel).getByText('Accessibility Standards Report')).toBeInTheDocument()
    expect(within(panel).getByText('18 June 2026')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Title/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open original page/ })).toHaveAttribute('target', '_blank')
    expect(screen.getByRole('img', { name: /Original PDF page .* evidence/ })).toBeInTheDocument()

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
  })
})
