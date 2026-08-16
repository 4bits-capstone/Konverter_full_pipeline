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
  it('uses the same native details rows as the accessible HTML', async () => {
    const { container } = renderPreview()

    await screen.findByRole('heading', { name: 'Contents' })
    const rows = Array.from(
      container.querySelectorAll<HTMLDetailsElement>('details.publication-contents-item'),
    )
    const firstChapter = rows.find((row) => row.textContent?.includes('1. Introduction'))!
    const secondChapter = rows.find((row) => row.textContent?.includes('2. Requirements'))!

    expect(firstChapter).not.toHaveAttribute('open')
    expect(secondChapter).not.toHaveAttribute('open')

    fireEvent.click(firstChapter.querySelector('summary')!)
    expect(firstChapter).toHaveAttribute('open')
    expect(screen.getByRole('link', { name: 'Purpose' })).toBeVisible()
    expect(screen.queryByRole('link', { name: 'Background' })).not.toBeInTheDocument()

    fireEvent.click(secondChapter.querySelector('summary')!)
    expect(secondChapter).toHaveAttribute('open')
    expect(screen.getByRole('link', { name: 'Semantic output' })).toBeVisible()
  })

  it('opens front matter directly instead of rendering it as an accordion', async () => {
    renderPreview()

    const preface = await screen.findByRole('link', { name: 'Preface' })
    expect(screen.queryByRole('button', { name: 'Preface' })).not.toBeInTheDocument()

    fireEvent.click(preface)
    expect(screen.getByRole('heading', { level: 1, name: 'Preface' })).toBeInTheDocument()
    expect(screen.getByText('This preface introduces the publication.')).toBeInTheDocument()
  })

  it('opens Chapter 1 content and returns to the publication landing page', async () => {
    renderPreview()
    const chapterSummary = await screen.findByText('1. Introduction')
    fireEvent.click(chapterSummary.closest('summary')!)

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    fireEvent.click(screen.getByRole('link', { name: 'Purpose' }))

    expect(screen.getByRole('heading', { level: 1, name: '1. Introduction' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Purpose' })).toBeInTheDocument()
    expect(screen.getByText(/defines a review workflow/)).toBeInTheDocument()
    const paragraphNumber = screen.getByText('1.2')
    expect(paragraphNumber.parentElement).toHaveClass('numbered-paragraph')
    expect(paragraphNumber.nextElementSibling).toHaveTextContent(/Every flagged structure/)
    expect(screen.getByRole('link', { name: 'Purpose' })).toHaveAttribute('aria-current', 'location')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)

    fireEvent.click(screen.getByRole('link', { name: 'Accessibility Standards Report' }))

    expect(screen.getByRole('heading', { level: 1, name: 'Accessibility Standards Report' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Contents' })).toBeInTheDocument()
    expect(document.querySelector('.konverter-page-menu')).toBeInTheDocument()
  })

  it('opens the selected subsection in the reader navigation', async () => {
    const scrollTo = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollTo,
    })
    renderPreview()
    const chapterSummary = await screen.findByText('1. Introduction')
    fireEvent.click(chapterSummary.closest('summary')!)

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
    expect(screen.getByRole('button', { name: /Start new upload/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Open public page/ })).not.toBeInTheDocument()

    const contents = document.querySelector('.konverter-page-menu')!
    expect(Array.from(contents.children).map((item) => item.querySelector('a, summary')?.textContent?.trim())).toEqual([
      'Preface',
      '1. Introduction',
      '2. Requirements',
      'Appendices',
      'Bibliography',
    ])

    const backToTop = screen.getByRole('button', { name: 'Back to top of page' })
    expect(backToTop).not.toHaveClass('is-visible')
    const scrollContainer = document.getElementById('main-content')!
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 600 })
    fireEvent.scroll(scrollContainer)
    expect(backToTop).toHaveClass('is-visible')

    fireEvent.click(screen.getByText('Export'))
    expect(screen.getByRole('menuitem', { name: /Accessible HTML/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /JSON-LD/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /Structured JSON/ })).toBeInTheDocument()

    expect(screen.getByRole('heading', { level: 1, name: 'Accessibility Standards Report' })).toBeInTheDocument()
    expect(screen.getByText('June 18, 2026')).toBeInTheDocument()
    expect(screen.getByText(/practical requirements for producing accessible/)).toBeInTheDocument()
    expect(screen.getByText('2. Requirements').closest('summary')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Download PDF/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Go to Project/ })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'VLRC website' })).not.toBeInTheDocument()
    expect(document.querySelector('.vlrc-masthead')).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
    expect(document.querySelector('.preview-report-card')).not.toBeInTheDocument()
    expect(document.querySelector('.vlrc-accordion')).not.toBeInTheDocument()
  })

  it('embeds the generated JSON-LD while the landing page preview is open', async () => {
    renderPreview()
    const chapterSummary = await screen.findByText('1. Introduction')
    fireEvent.click(chapterSummary.closest('summary')!)

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
