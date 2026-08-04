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
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ReviewPage', () => {
  it('explains structure confidence and provides the requested queue controls', async () => {
    renderReview()

    expect(screen.getByText('How to review structure confidence flags')).toBeInTheDocument()
    expect(screen.getByLabelText('Search queue')).toBeInTheDocument()
    expect(screen.getByLabelText('Status')).toHaveValue('all')
    expect(screen.getByLabelText('Filter by structure label')).toHaveValue('all')
    expect(screen.getByLabelText('Sort')).toHaveValue('highest')
    expect(screen.queryByLabelText('Confidence')).not.toBeInTheDocument()

    await screen.findAllByText('Section heading needs confirmation')
    expect(screen.getByRole('button', { name: /Remove from output/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Needs attention/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Accept all/ })).not.toBeInTheDocument()
  })

  it('locks text and structure controls until Edit is selected', async () => {
    renderReview()
    await screen.findAllByText('Section heading needs confirmation')
    fireEvent.click(screen.getByRole('button', { name: /Section heading needs confirmation/ }))

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

    fireEvent.click(screen.getByRole('button', { name: /Definitions table needs confirmation/ }))
    expect(screen.getByRole('region', { name: /^Table;/ })).toBeInTheDocument()
    expect(screen.queryByText('Extracted table')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /Editable corrected table/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Edit flagged item' }))
    expect(screen.getByRole('region', { name: /Editable corrected table/ })).toBeInTheDocument()
    const definitionCell = screen.getByRole('textbox', { name: 'Row 1, Definition' })
    fireEvent.change(screen.getByRole('textbox', { name: 'Table caption (optional)' }), { target: { value: 'Definitions' } })
    fireEvent.change(definitionCell, { target: { value: 'Updated accessible-format definition' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add row' }))
    expect(screen.getByRole('textbox', { name: 'Row 4, Term' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.getByText('Updated accessible-format definition')).toBeInTheDocument())
    expect(await screen.findByRole('region', { name: /Definitions/ })).toBeInTheDocument()
  })

  it('searches extracted table text and converts a table into semantic list items', async () => {
    renderReview()
    await screen.findAllByText('Definitions table needs confirmation')

    fireEvent.change(screen.getByLabelText('Search queue'), { target: { value: 'Semantic structure' } })
    expect(screen.getByRole('button', { name: /Definitions table needs confirmation/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Section heading needs confirmation/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Definitions table needs confirmation/ }))
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

    fireEvent.click(screen.getByRole('button', { name: /Definitions table needs confirmation/ }))
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

  it('selects all visible flags and confirms a bulk structure change', async () => {
    renderReview()
    await screen.findAllByText('Section heading needs confirmation')

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Select all visible' }))
    expect(screen.getByText('3 selected')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)
    fireEvent.change(screen.getByLabelText('Bulk action'), { target: { value: 'label' } })
    fireEvent.change(screen.getByLabelText('Bulk structure label'), { target: { value: 'section_header_1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply to 3 selected' }))

    expect(screen.getByRole('alertdialog')).toHaveTextContent('Change 3 selected items to H1?')
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => {
      const queueButtons = screen.getAllByRole('button', { name: /needs confirmation/ })
      expect(queueButtons.every((button) => button.textContent?.includes('H1'))).toBe(true)
    })
    expect(screen.getByText('3 selected')).toBeInTheDocument()
  })

  it('supports Shift+click and Tab+click multi-selection without permanent checkboxes', async () => {
    renderReview()
    await screen.findAllByText('Section heading needs confirmation')
    const flags = screen.getAllByRole('button', { name: /needs confirmation/ })

    fireEvent.click(flags[0])
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    fireEvent.click(flags[2], { shiftKey: true })
    expect(screen.getByText('3 selected')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)

    fireEvent.click(screen.getByRole('button', { name: 'Clear visible selection' }))
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Tab' })
    fireEvent.click(flags[0])
    fireEvent.click(flags[1])
    fireEvent.keyUp(window, { key: 'Tab' })
    expect(screen.getByText('2 selected')).toBeInTheDocument()
  })

  it('accepts multiple selected flags through the in-app confirmation', async () => {
    renderReview()
    await screen.findAllByText('Section heading needs confirmation')

    fireEvent.click(screen.getByRole('button', { name: 'Select all visible' }))
    expect(screen.getByLabelText('Bulk action')).toHaveValue('accept')
    fireEvent.click(screen.getByRole('button', { name: 'Apply to 3 selected' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Accept 3 selected items?')
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      const queueButtons = screen.getAllByRole('button', { name: /needs confirmation/ })
      expect(queueButtons.every((button) => button.textContent?.includes('Accepted'))).toBe(true)
    })
  })

  it('keeps the filter and selects the next visible flag after a label change', async () => {
    renderReview()
    await screen.findAllByText('Section heading needs confirmation')

    fireEvent.change(screen.getByLabelText('Filter by structure label'), {
      target: { value: 'section_header_2' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Section heading needs confirmation/ }))
    expect(screen.getAllByText('Flag 1 of 2').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: 'Edit flagged item' }))
    fireEvent.change(screen.getByLabelText('Structure label'), {
      target: { value: 'section_header_3' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByRole('heading', { name: 'Secondary heading needs confirmation' })).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by structure label')).toHaveValue('section_header_2')
    expect(screen.getByLabelText('Sort')).toHaveValue('highest')
    expect(screen.getAllByText('Flag 1 of 1').length).toBeGreaterThan(0)
  })
})
