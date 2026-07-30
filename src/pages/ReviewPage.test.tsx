import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KonverterProvider, useKonverter } from '../state/KonverterContext'
import { testDocument } from '../test/fixtures'
import { resetTestServices } from '../test/serviceMocks'
import { ReviewPage } from './ReviewPage'

vi.mock('../services', () => import('../test/serviceMocks'))

function SeedCompletedDocument() {
  const { addDocuments } = useKonverter()
  useEffect(() => addDocuments([testDocument]), [addDocuments])
  return null
}

function renderReview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <KonverterProvider>
          <SeedCompletedDocument />
          <ReviewPage />
        </KonverterProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(resetTestServices)
afterEach(cleanup)

describe('ReviewPage', () => {
  it('explains structure confidence and provides the requested queue controls', async () => {
    renderReview()

    expect(screen.getByText('How to review structure confidence flags')).toBeInTheDocument()
    expect(screen.getByLabelText('Search queue')).toBeInTheDocument()
    expect(screen.getByLabelText('Status')).toHaveValue('all')
    expect(screen.getByLabelText('Filter by structure label')).toHaveValue('all')
    expect(screen.getByLabelText('Sort')).toHaveValue('highest')

    await screen.findAllByText('Section heading needs confirmation')
    expect(screen.getByRole('button', { name: /Remove from output/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Needs attention/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Accept all/ })).not.toBeInTheDocument()
  })

  it('locks text and structure controls until Edit is selected', async () => {
    renderReview()
    await screen.findAllByText('Section heading needs confirmation')
    fireEvent.click(screen.getByRole('option', { name: /Section heading needs confirmation/ }))

    expect(screen.getByText('Extracted result (reference only)')).toBeInTheDocument()
    expect(screen.getByLabelText('Structure label')).toHaveValue('section_header_2')
    expect(screen.getByLabelText('Structure label')).toBeDisabled()
    expect(screen.queryByRole('textbox', { name: 'Corrected text' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Edit flagged item' }))
    expect(screen.getByLabelText('Structure label')).toBeEnabled()
    expect(screen.getByRole('textbox', { name: 'Corrected text' })).toHaveValue('Purpose')
    expect(screen.getByRole('link', { name: /Open original page/ })).toHaveAttribute('target', '_blank')
    expect(screen.getByRole('button', { name: 'Save changes' })).toHaveClass('btn-primary')
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })

  it('provides a cell-based editor for flagged tables', async () => {
    renderReview()
    await screen.findAllByText('Definitions table needs confirmation')

    fireEvent.click(screen.getByRole('option', { name: /Definitions table needs confirmation/ }))
    expect(screen.getByRole('region', { name: /Extracted table/ })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /Editable corrected table/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Edit flagged item' }))
    expect(screen.getByRole('region', { name: /Editable corrected table/ })).toBeInTheDocument()
    const definitionCell = screen.getByRole('textbox', { name: 'Row 1, Definition' })
    fireEvent.change(definitionCell, { target: { value: 'Updated accessible-format definition' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add row' }))
    expect(screen.getByRole('textbox', { name: 'Row 4, Term' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.getByText('Updated accessible-format definition')).toBeInTheDocument())
    expect(await screen.findByRole('region', { name: /Saved corrected table/ })).toBeInTheDocument()
  })

  it('searches extracted table text and converts a table into semantic list items', async () => {
    renderReview()
    await screen.findAllByText('Definitions table needs confirmation')

    fireEvent.change(screen.getByLabelText('Search queue'), { target: { value: 'Semantic structure' } })
    expect(screen.getByRole('option', { name: /Definitions table needs confirmation/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Section heading needs confirmation/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('option', { name: /Definitions table needs confirmation/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit flagged item' }))
    fireEvent.change(screen.getByLabelText('Structure label'), { target: { value: 'list' } })

    expect(screen.getByRole('group', { name: 'Editable corrected list' })).toBeInTheDocument()
    const firstListItem = screen.getByLabelText('List item 1') as HTMLTextAreaElement
    expect(firstListItem.value).toContain('Accessible format — Content that people can perceive')
    expect(firstListItem.value).not.toContain('|')
    expect(screen.queryByText('Term | Definition')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Editable corrected list' })).not.toBeInTheDocument())
    expect(screen.getByLabelText('Structure label')).toHaveValue('list')
  })

  it('converts a table directly into footnote prose without table delimiters', async () => {
    renderReview()
    await screen.findAllByText('Definitions table needs confirmation')

    fireEvent.click(screen.getByRole('option', { name: /Definitions table needs confirmation/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit flagged item' }))
    fireEvent.change(screen.getByLabelText('Structure label'), { target: { value: 'footnote' } })

    const correction = screen.getByRole('textbox', { name: 'Corrected text' }) as HTMLTextAreaElement
    await waitFor(() => expect(correction.value).toContain('Term: Accessible format; Definition: Content that people can perceive'))
    expect(correction.value).not.toContain('|')
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Corrected text' })).not.toBeInTheDocument())
    expect(screen.getByLabelText('Structure label')).toHaveValue('footnote')
  })

  it('removes unnecessary content from output and allows it to be restored', async () => {
    renderReview()
    await screen.findAllByText('Section heading needs confirmation')

    fireEvent.click(screen.getByRole('button', { name: 'Remove from output' }))
    const restore = await screen.findByRole('button', { name: 'Restore to output' })
    fireEvent.click(restore)
    expect(await screen.findByText('Accepted')).toBeInTheDocument()
  })
})
