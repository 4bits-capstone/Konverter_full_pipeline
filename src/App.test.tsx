import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { KonverterProvider } from './state/KonverterContext'
import { resetTestServices } from './test/serviceMocks'

vi.mock('./services', () => import('./test/serviceMocks'))

vi.mock('./lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({
        data: { session: { access_token: 'test-token', user: { id: 'test-user', email: 'test@example.com' } } },
      }),
      onAuthStateChange: vi.fn().mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } }),
      signOut: vi.fn().mockResolvedValue({ error: null }),
    },
  },
}))

function renderApp(initialPath = '/upload') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <KonverterProvider>
          <App />
        </KonverterProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
})
beforeEach(resetTestServices)

describe('Konverter frontend', () => {
  it('renders the upload stage and pipeline navigation', async () => {
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Upload documents' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Review pipeline' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Step 2: Review/i })).toBeDisabled()
  })

  it('uses the reviewer console as the only application entry point', async () => {
    renderApp('/reports/previous-public-route')
    expect(await screen.findByRole('heading', { name: 'Upload documents' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Primary navigation' })).not.toBeInTheDocument()
  })

  it('accepts multiple PDFs and lets the reviewer choose one', async () => {
    const { container } = renderApp()
    await screen.findByRole('heading', { name: 'Upload documents' })
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')
    expect(input).toHaveAttribute('multiple')

    const first = new File(['first'], 'first-report.pdf', { type: 'application/pdf', lastModified: 1 })
    const second = new File(['second'], 'second-report.pdf', { type: 'application/pdf', lastModified: 2 })
    fireEvent.change(input!, { target: { files: [first, second] } })

    expect(await screen.findByRole('radiogroup', { name: 'Choose document to review' })).toBeInTheDocument()
    expect(screen.getAllByRole('radio')).toHaveLength(2)
    expect(screen.getAllByText('first-report.pdf')).not.toHaveLength(0)
    expect(screen.getAllByText('second-report.pdf')).not.toHaveLength(0)
  })

  it('limits the active queue to five documents', async () => {
    const { container } = renderApp()
    await screen.findByRole('heading', { name: 'Upload documents' })
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')
    const files = Array.from({ length: 6 }, (_, index) => (
      new File([`${index}`], `report-${index + 1}.pdf`, {
        type: 'application/pdf',
        lastModified: index,
      })
    ))

    fireEvent.change(input!, { target: { files } })

    expect(await screen.findAllByRole('radio')).toHaveLength(5)
    expect(screen.queryByText('report-6.pdf')).not.toBeInTheDocument()
    expect(screen.getByText(/Only 5 were added because the limit is 5/)).toBeInTheDocument()
  })

  it('processes an uploaded document and opens its review queue', async () => {
    const { container } = renderApp()
    await screen.findByRole('heading', { name: 'Upload documents' })
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')
    const first = new File(['first'], 'first-report.pdf', { type: 'application/pdf', lastModified: 1 })
    fireEvent.change(input!, { target: { files: [first] } })
    fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
    await screen.findAllByText('Ready to review')
    fireEvent.click(screen.getByRole('button', { name: 'Review now' }))
    expect(await screen.findByRole('heading', { name: 'Review' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Document')).not.toBeInTheDocument()
    expect(screen.getAllByText('first-report.pdf').length).toBeGreaterThan(0)
  })

  it('does not expose sample or demo shortcuts', async () => {
    renderApp()
    await waitFor(() => {
      expect(screen.queryByText(/sample|demo|prototype/i)).not.toBeInTheDocument()
    })
  })
})
