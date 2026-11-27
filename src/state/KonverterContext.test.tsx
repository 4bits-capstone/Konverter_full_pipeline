import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KonverterProvider, useKonverter } from './KonverterContext'
import { testDocument } from '../test/fixtures'
import { documentService, resetTestServices } from '../test/serviceMocks'

vi.mock('../services', () => import('../test/serviceMocks'))

function Harness() {
  const { documents, addDocuments, removeDocument, toastState } = useKonverter()
  return (
    <>
      <button type="button" onClick={() => addDocuments([testDocument])}>Seed</button>
      <button type="button" onClick={() => removeDocument(testDocument.id)}>Remove</button>
      <ul>
        {documents.map((document) => <li key={document.id}>{document.fileName}</li>)}
      </ul>
      <div data-testid="toast-probe">{toastState?.message ?? ''}</div>
    </>
  )
}

function renderHarness() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <KonverterProvider>
        <Harness />
      </KonverterProvider>
    </QueryClientProvider>,
  )
}

beforeEach(resetTestServices)
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('removeDocument', () => {
  it('shows an error and restores the document from the server when delete fails', async () => {
    vi.spyOn(documentService, 'removeDocument').mockRejectedValue(new Error('storage unavailable'))
    vi.spyOn(documentService, 'listDocuments').mockResolvedValue([testDocument])
    renderHarness()

    fireEvent.click(screen.getByRole('button', { name: 'Seed' }))
    expect(screen.getByText(testDocument.fileName)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))

    expect(await screen.findByTestId('toast-probe')).toHaveTextContent(
      'This document could not be removed. Please try again.',
    )
    await waitFor(() => expect(screen.getByText(testDocument.fileName)).toBeInTheDocument())
    expect(documentService.listDocuments).toHaveBeenCalled()
  })
})
