import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { KonverterProvider, useKonverter } from './state/KonverterContext'
import { supabase } from './lib/supabaseClient'
import { resetTestServices } from './test/serviceMocks'
import { testDocument } from './test/fixtures'

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

function SeedApprovedDocument() {
  const { addDocuments } = useKonverter()
  useEffect(() => addDocuments([{ ...testDocument, approvedAt: '2026-08-28T00:00:00Z' }]), [addDocuments])
  return null
}

function renderApp(initialPath = '/upload', seedApproved = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <KonverterProvider>
          {seedApproved && <SeedApprovedDocument />}
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
    expect(await screen.findByRole('heading', { name: 'Upload documents' }, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Review pipeline' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Step 2: Review/i })).toBeDisabled()
    expect(screen.getByText('Helping businesses use AI to be more efficient and effective.')).toBeInTheDocument()
    expect(screen.getByText('Convert, review and export')).toBeInTheDocument()
  })

  it('shows the updated login copy without remember-me or password-recovery controls', async () => {
    vi.mocked(supabase.auth.getSession).mockResolvedValueOnce({
      data: { session: null },
      error: null,
    })

    renderApp()

    expect(await screen.findByRole('heading', { name: 'Sign in to continue' })).toBeInTheDocument()
    expect(screen.getByText('Reviewer console')).toBeInTheDocument()
    expect(screen.getByText('Use your Konverter account to convert, review and export accessible reports.')).toBeInTheDocument()
    expect(screen.getByText('Helping businesses use AI to be more efficient and effective.')).toBeInTheDocument()
    expect(screen.queryByText(/remember me/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/forgot password/i)).not.toBeInTheDocument()
  })

  it('keeps History in settings without an extra header button', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Upload documents' })
    const utilities = screen.getByRole('group', { name: 'Help and account' })
    expect(utilities.querySelectorAll(':scope > a')).toHaveLength(0)
    fireEvent.click(utilities.querySelector('summary[aria-label="Account settings"]')!)
    expect(screen.getByRole('link', { name: 'History' })).toHaveAttribute('href', '/history')
  })

  it('restores Preview and keeps the previous export URL working', async () => {
    renderApp('/export', true)
    expect(await screen.findByRole('heading', { name: 'Preview converted document' }, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Step 4: Preview/ })).toHaveAttribute('aria-current', 'step')
    expect(await screen.findByRole('link', { name: 'Open report' })).toHaveAttribute('href', '/report/test-document')
    expect(screen.getByRole('img', { name: 'Komosion' })).toHaveAttribute('src', '/komosion-wordmark-reversed.png')
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
