import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KonverterProvider, useKonverter } from '../state/KonverterContext'
import { testDocument, testMetadata } from '../test/fixtures'
import { resetTestServices } from '../test/serviceMocks'
import { ApprovalPage } from './ApprovalPage'

vi.mock('../services', () => import('../test/serviceMocks'))

function SeedApprovalDocument() {
  const { addDocuments, setMetadata } = useKonverter()
  useEffect(() => {
    addDocuments([testDocument])
    setMetadata(testMetadata)
  }, [addDocuments, setMetadata])
  return null
}

function renderApproval() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <KonverterProvider>
          <SeedApprovalDocument />
          <ApprovalPage />
        </KonverterProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(resetTestServices)
afterEach(cleanup)

describe('ApprovalPage', () => {
  it('keeps the final Resolve all control without demo behavior', async () => {
    renderApproval()
    await screen.findByText(/flagged items reviewed/i)

    const resolveAll = screen.getByRole('button', { name: 'Resolve all' })
    expect(screen.queryByText(/demo|sample|prototype/i)).not.toBeInTheDocument()
    fireEvent.click(resolveAll)

    expect(await screen.findByText('All 2 items reviewed')).toBeInTheDocument()
  })
})
