import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KonverterProvider, useKonverter } from '../state/KonverterContext'
import { testDocument } from '../test/fixtures'
import { resetTestServices } from '../test/serviceMocks'
import { PreviewPage } from './PreviewPage'

vi.mock('../services', () => import('../test/serviceMocks'))

function SeedCompletedDocument() {
  const { addDocuments } = useKonverter()
  useEffect(() => addDocuments([testDocument]), [addDocuments])
  return null
}

function renderPreview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <KonverterProvider>
          <SeedCompletedDocument />
          <main id="main-content">
            <PreviewPage />
          </main>
        </KonverterProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(cleanup)
beforeEach(resetTestServices)

describe('PreviewPage', () => {
  it('expands and collapses publication chapters accessibly', async () => {
    renderPreview()

    const firstChapter = await screen.findByRole('button', { name: '1. Introduction' })
    const secondChapter = screen.getByRole('button', { name: '2. Requirements' })

    expect(firstChapter).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Purpose' })).toBeVisible()
    expect(screen.queryByRole('link', { name: 'Background' })).not.toBeInTheDocument()
    expect(secondChapter).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(secondChapter)
    expect(secondChapter).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Semantic output' })).toBeVisible()

    fireEvent.click(firstChapter)
    expect(firstChapter).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Purpose' })).not.toBeInTheDocument()
  })

  it('opens Chapter 1 content and returns to the publication landing page', async () => {
    renderPreview()
    await screen.findByRole('button', { name: '1. Introduction' })

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    fireEvent.click(screen.getByRole('link', { name: 'Purpose' }))

    expect(screen.getByRole('heading', { level: 1, name: '1. Introduction' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Purpose' })).toBeInTheDocument()
    expect(screen.getByText(/defines a review workflow/)).toBeInTheDocument()
    const paragraphNumber = screen.getByText('1.2')
    expect(paragraphNumber).toHaveClass('reader-paragraph-number')
    expect(paragraphNumber.nextElementSibling).toHaveTextContent(/Every flagged structure/)
    expect(screen.getByRole('link', { name: 'Purpose' })).toHaveAttribute('aria-current', 'location')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'Accessibility Standards Report' }))

    expect(screen.getByRole('heading', { level: 1, name: 'Accessibility Standards Report' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Document chapters' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Contents' })).not.toBeInTheDocument()
  })

  it('opens the selected subsection in the reader navigation', async () => {
    const scrollTo = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollTo,
    })
    renderPreview()
    await screen.findByRole('button', { name: '1. Introduction' })

    fireEvent.click(screen.getByRole('link', { name: 'Purpose' }))

    expect(screen.getByRole('link', { name: 'Purpose' })).toHaveAttribute('aria-current', 'location')
    expect(screen.getByText(/defines a review workflow/)).toBeInTheDocument()
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })

    delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo
  })

  it('uses one export menu and exposes the generated report from the landing page', async () => {
    renderPreview()

    expect(await screen.findByText('Export')).toBeInTheDocument()
    expect(screen.getByText(/Reviewed Docling data is loaded: 12 pages/)).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Preview navigation' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Return to review/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Return to metadata/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('Export'))
    expect(screen.getByRole('menuitem', { name: /Accessible HTML/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /JSON-LD/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /Structured JSON/ })).toBeInTheDocument()

    expect(screen.getByRole('heading', { level: 1, name: 'Accessibility Standards Report' })).toBeInTheDocument()
    expect(screen.getByText('Published on June 18, 2026.')).toBeInTheDocument()
    expect(screen.getByText(/practical requirements for producing accessible/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2. Requirements' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download PDF' })).toBeInTheDocument()
  })

  it('embeds the generated JSON-LD while the landing page preview is open', async () => {
    renderPreview()
    await screen.findByRole('button', { name: '1. Introduction' })

    const jsonLdScript = document.head.querySelector<HTMLScriptElement>('#konverter-publication-json-ld')
    expect(jsonLdScript).not.toBeNull()
    expect(jsonLdScript).toHaveAttribute('type', 'application/ld+json')
    expect(JSON.parse(jsonLdScript?.textContent ?? '{}')).toMatchObject({
      '@context': 'https://schema.org',
      '@graph': expect.arrayContaining([
        expect.objectContaining({
          '@type': 'Report',
          name: 'Accessibility Standards Report',
        }),
      ]),
    })

    fireEvent.click(screen.getByRole('link', { name: 'Purpose' }))
    expect(document.head.querySelector('#konverter-publication-json-ld')).not.toBeNull()
  })
})
