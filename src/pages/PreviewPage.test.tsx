import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KonverterProvider, useKonverter } from '../state/KonverterContext'
import { testDocument } from '../test/fixtures'
import { publicationService, resetTestServices } from '../test/serviceMocks'
import { PreviewPage } from './PreviewPage'
import { ReportPage } from './ReportPage'

vi.mock('../services', () => import('../test/serviceMocks'))
vi.mock('../components/DocumentChat', () => ({ DocumentChat: () => <div>Report chatbot</div> }))

function SeedCompletedDocument() {
  const { addDocuments } = useKonverter()
  useEffect(() => addDocuments([testDocument]), [addDocuments])
  return null
}
function renderPreview(path = '/preview') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[path]}><KonverterProvider>
    <SeedCompletedDocument />
    <Routes><Route path="preview" element={<PreviewPage />} /><Route path="report/:documentId" element={<ReportPage />} /><Route path="upload" element={<h1>Upload</h1>} /></Routes>
  </KonverterProvider></MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
beforeEach(resetTestServices)

describe('Preview and report pages', () => {
  it('shows an embedded publication preview and the three existing downloads', async () => {
    renderPreview()
    expect(await screen.findByText('Conversion complete')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Preview converted document' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Download files' }))
    const links = within(screen.getByRole('group', { name: 'Export formats' })).getAllByRole('link')
    expect(links).toHaveLength(3)
    expect(links.map(link => link.getAttribute('href'))).toEqual([
      '/api/documents/test-document/exports/html', '/api/documents/test-document/exports/jsonld', '/api/documents/test-document/exports/structured',
    ])
    expect(screen.queryByText('Cosmograph')).not.toBeInTheDocument()
    expect(screen.queryByText('Original PDF')).not.toBeInTheDocument()
    const preview = await screen.findByTitle('Accessible publication preview: Accessibility Standards Report')
    expect(preview).toHaveAttribute('sandbox', 'allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads')
    expect(preview.getAttribute('srcdoc')).toContain('<blockquote>Reviewed quotation.</blockquote>')
    expect(screen.getByText('June 18, 2026')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Return to review' })).toHaveAttribute('href', '/review')
  })

  it('opens the canonical HTML in a separate report route and retains JSON-LD and chat', async () => {
    const getHtml = vi.spyOn(publicationService, 'getHtml')
    renderPreview()
    fireEvent.click(await screen.findByRole('link', { name: 'Open report' }))
    const frame = await screen.findByTitle('Accessibility Standards Report')
    expect(getHtml).toHaveBeenCalledWith('test-document')
    expect(frame.tagName).toBe('IFRAME')
    expect(frame.getAttribute('srcdoc')).toContain('<blockquote>Reviewed quotation.</blockquote>')
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin')
    expect(screen.getByText('Report chatbot')).toBeInTheDocument()
    expect(document.head.querySelector('#konverter-publication-json-ld')).not.toBeNull()
    fireEvent.click(screen.getByRole('link', { name: 'Back to preview' }))
    expect(await screen.findByText('Conversion complete')).toBeInTheDocument()
    expect(document.head.querySelector('#konverter-publication-json-ld')).toBeNull()
  })

  it('loads a report directly by its document ID and removes duplicate embedded chat', async () => {
    vi.spyOn(publicationService, 'getHtml').mockResolvedValue('<html><head></head><body><h1>Report</h1><script data-konverter-chat>window.__KONVERTER_CHAT__={};</script><blockquote>Quote.</blockquote></body></html>')
    renderPreview('/report/another-document')
    const frame = await screen.findByTitle('Accessibility Standards Report')
    expect(publicationService.getHtml).toHaveBeenCalledWith('another-document')
    expect(frame.getAttribute('srcdoc')).not.toContain('__KONVERTER_CHAT__')
    expect(frame.getAttribute('srcdoc')).toContain('<blockquote>Quote.</blockquote>')
  })

  it('allows retry when the approved report cannot be loaded', async () => {
    vi.spyOn(publicationService, 'getHtml').mockRejectedValueOnce(new Error('Unavailable'))
    renderPreview('/report/test-document')
    expect(await screen.findByRole('alert')).toHaveTextContent('report could not be loaded')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByTitle('Accessibility Standards Report')).toBeInTheDocument()
  })


  it('closes the download dropdown on Escape, outside click, blur and selection', async () => {
    renderPreview()
    const trigger = await screen.findByRole('button', { name: 'Download files' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(trigger).toHaveFocus()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('group', { name: 'Export formats' })).not.toBeInTheDocument()
    fireEvent.click(trigger)
    fireEvent.blur(trigger, { relatedTarget: screen.getByRole('link', { name: 'Open report' }) })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    const download = screen.getByRole('link', { name: /JSON-LD Structured metadata/ })
    download.addEventListener('click', event => event.preventDefault(), { once: true })
    fireEvent.click(download)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('keeps Open report beside the dropdown and uses the same publication HTML in both views', async () => {
    renderPreview()
    const preview = await screen.findByTitle('Accessible publication preview: Accessibility Standards Report')
    const source = preview.getAttribute('srcdoc')
    const actions = screen.getByRole('group', { name: 'Downloads and report' })
    expect(within(actions).getByRole('button', { name: 'Download files' })).toBeInTheDocument()
    fireEvent.click(within(actions).getByRole('link', { name: 'Open report' }))
    const report = await screen.findByTitle('Accessibility Standards Report')
    expect(report.getAttribute('srcdoc')).toBe(source)
  })

  it('can retry the embedded preview without removing the download controls', async () => {
    vi.spyOn(publicationService, 'getHtml').mockRejectedValueOnce(new Error('Unavailable'))
    renderPreview()
    expect(await screen.findByRole('alert')).toHaveTextContent('report could not be loaded')
    expect(screen.getByRole('button', { name: 'Download files' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByTitle('Accessible publication preview: Accessibility Standards Report')).toBeInTheDocument()
  })

  it('starts a new upload from the preview page', async () => {
    renderPreview()
    await screen.findByText('Conversion complete')
    fireEvent.click(screen.getByRole('button', { name: 'Start new upload' }))
    expect(screen.getByRole('heading', { name: 'Upload' })).toBeInTheDocument()
  })
})

// Exercise the actual optional report script independently of the React shell.
import reportScript from '../../backend/app/static/report/report.js?raw'

it('navigates generated report views, opens footnotes and copies the actual citation', async () => {
  document.body.innerHTML = `<div data-konverter-publication>
    <input class="vlrc-view-toggle" id="vlrc-view-landing" type="radio" name="view" checked />
    <input class="vlrc-view-toggle" id="vlrc-view-first" data-reader="reader-first" type="radio" name="view" />
    <div id="publication-landing"><h1 id="publication-title">Report</h1><h2 id="contents-heading">Contents</h2><a href="#purpose">Read purpose</a>
      <button class="report-copy-citation" data-citation="Example Publisher, A Different Report (2025).">Copy citation</button><span class="citation-copy-status"></span>
    </div>
    <section class="vlrc-reader" id="reader-first"><div class="vlrc-reader-content"><h1 id="reader-title-first">First chapter</h1><h2 id="purpose">Purpose</h2>
      <a href="#footnote-1">1</a><details><summary>Footnotes</summary><p id="footnote-1">Source</p></details><a class="breadcrumb-publication-link" href="#contents-heading">Back</a>
    </div><nav class="vlrc-reader-nav"><h2>In this section</h2><ul id="first-links"><li><a href="#purpose">Purpose</a></li></ul></nav></section>
  </div>`
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { callback(0); return 0 })
  const scroll = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll })
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
  window.eval(reportScript)
  fireEvent.click(screen.getByRole('link', { name: 'Read purpose' }))
  expect((document.getElementById('vlrc-view-first') as HTMLInputElement).checked).toBe(true)
  expect(screen.getByRole('link', { name: 'Purpose' })).toHaveAttribute('aria-current', 'location')
  fireEvent.click(screen.getByRole('link', { name: '1' }))
  expect(document.querySelector('details')).toHaveAttribute('open')
  fireEvent.click(screen.getByRole('link', { name: 'Back' }))
  expect((document.getElementById('vlrc-view-landing') as HTMLInputElement).checked).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Copy citation' }))
  expect(writeText).toHaveBeenCalledWith('Example Publisher, A Different Report (2025).')
  expect(scroll).toHaveBeenCalled()
  window.history.replaceState({}, '', '/')
  document.body.innerHTML = ''
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView
})

import reportTemplateSource from '../../backend/app/preview_html.py?raw'

it('uses the selected reader only when scripts are stripped by the host', () => {
  const fallback = reportTemplateSource.match(/SCRIPT_FREE_STYLE = r"""([\s\S]*?)"""/)![1]
  // JSDOM does not evaluate media queries; apply the real screen rules directly.
  const rules = fallback.replace('@media screen {', '').trim().replace(/\}$/, '')
  const style = document.createElement('style')
  style.textContent = '.vlrc-reader {display:none}' + rules
  document.head.appendChild(style)
  document.body.innerHTML = `<div class="vlrc-publication-embed"><section id="publication-landing">Overview</section><section class="vlrc-reader" id="reader-one"><h2 id="selected-heading">Selected heading</h2></section><section class="vlrc-reader" id="reader-two">Other section</section></div>`
  window.history.replaceState({}, '', '/#selected-heading')
  expect(getComputedStyle(document.getElementById('publication-landing')!).display).toBe('none')
  expect(getComputedStyle(document.getElementById('reader-one')!).display).toBe('block')
  expect(getComputedStyle(document.getElementById('reader-two')!).display).toBe('none')
  style.remove()
  window.history.replaceState({}, '', '/')
  document.body.innerHTML = ''
})
