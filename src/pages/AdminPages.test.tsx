import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { KonverterProvider } from '../state/KonverterContext'
import { auditService, documentService, resetTestServices } from '../test/serviceMocks'
import { testDocument } from '../test/fixtures'
import type { AuditLogEntry, DocumentSummary } from '../types/konverter'
import { AdminOverviewPage } from './AdminOverviewPage'
import { AuditLogPage } from './AuditLogPage'
import { DocumentListPage } from './DocumentListPage'

vi.mock('../services', () => import('../test/serviceMocks'))

const documents: DocumentSummary[] = [
  { ...testDocument, uploadedAt: '2026-08-20T09:00:00Z', uploadedByEmail: 'owner@example.com' },
  { ...testDocument, id: 'failed-document', title: 'Failed report', fileName: 'failed-report.pdf', processingState: 'failed', uploadedAt: '2026-08-21T09:00:00Z', uploadedByEmail: 'owner@example.com' },
  { ...testDocument, id: 'approved-document', title: 'Approved report', approvedAt: '2026-08-22T09:00:00Z', uploadedByEmail: 'owner@example.com' },
]
const entries: AuditLogEntry[] = [
  { id: 3, document_id: 'failed-document', actor_id: 'reviewer', actor_email: 'reviewer@example.com', action: 'process_failed', detail: { error: 'Extraction failed', file_name: 'failed-report.pdf' }, created_at: '2026-08-23T09:00:00Z', entry_hash: 'hash-3', prev_hash: 'hash-2' },
  { id: 2, document_id: testDocument.id, actor_id: 'reviewer', actor_email: 'reviewer@example.com', action: 'edit_metadata', detail: { before: { title: 'Old title' }, after: { title: testDocument.title } }, created_at: '2026-08-22T09:00:00Z', entry_hash: 'hash-2', prev_hash: 'hash-1' },
  { id: 1, document_id: testDocument.id, actor_id: 'owner', actor_email: 'owner@example.com', action: 'upload', detail: { file_name: testDocument.fileName }, created_at: '2026-08-20T09:00:00Z', entry_hash: 'hash-1', prev_hash: '0'.repeat(64) },
]
function renderAdmin(path = '/admin/overview') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[path]}><KonverterProvider><Routes>
    <Route path="admin/overview" element={<AdminOverviewPage />} />
    <Route path="admin/documents" element={<DocumentListPage />} />
    <Route path="admin/audit-log" element={<AuditLogPage />} />
    <Route path="review" element={<h1>Review route</h1>} />
    <Route path="preview" element={<h1>Preview route</h1>} />
  </Routes></KonverterProvider></MemoryRouter></QueryClientProvider>)
}
beforeEach(() => {
  resetTestServices()
  vi.spyOn(documentService, 'listAllDocuments').mockResolvedValue(documents)
  vi.spyOn(auditService, 'list').mockResolvedValue(entries)
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Admin console preserves the original workflow', () => {
  it('keeps the original tab headings, descriptions and metric definitions', async () => {
    renderAdmin()
    await screen.findByRole('table', { name: 'Recent audit activity' })
    const nav = screen.getByRole('navigation', { name: 'Admin views' })
    expect(within(nav).getByRole('link', { name: 'Overview At a glance' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Doc list All documents 3' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Audit log Secure record 3' })).toBeInTheDocument()
    const metrics = { 'Total documents': 3, 'Awaiting approval': 1, 'Processing failures': 1, Contributors: 1, 'Audit events': 3, 'Broken chain entries': 0 }
    for (const [label, value] of Object.entries(metrics)) {
      expect(screen.getByText(label).parentElement).toHaveTextContent(`${value}${label}`)
    }
    expect(within(screen.getByRole('table')).getAllByRole('columnheader').map(node => node.textContent)).toEqual(['Time', 'Actor', 'Action', 'Summary'])
    fireEvent.click(screen.getByRole('link', { name: 'View full audit log' }))
    expect(await screen.findByRole('heading', { name: 'Audit log' })).toBeInTheDocument()
  })

  it('keeps automatic document selection and the separate detail panel', async () => {
    renderAdmin('/admin/documents')
    const table = await screen.findByRole('table', { name: 'Document list' })
    const selected = await screen.findByRole('complementary', { name: 'Selected document details' })
    expect(selected.closest('tr')).toBeNull()
    expect(within(selected).getByRole('heading', { name: 'Failed report' })).toBeInTheDocument()
    fireEvent.click(within(table).getByRole('button', { name: testDocument.title }))
    expect(within(selected).getByRole('heading', { name: testDocument.title })).toBeInTheDocument()
    expect(within(table).getByRole('button', { name: testDocument.title })).toHaveAttribute('aria-current', 'true')
  })

  it('opens approved documents in Preview and disables opening incomplete documents', async () => {
    renderAdmin('/admin/documents')
    const selected = await screen.findByRole('complementary', { name: 'Selected document details' })
    expect(within(selected).getByRole('button', { name: 'Open' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Approved report' }))
    fireEvent.click(within(selected).getByRole('button', { name: 'Open' }))
    expect(screen.getByRole('heading', { name: 'Preview route' })).toBeInTheDocument()
  })

  it('retains document search, status, date range and sort controls', async () => {
    renderAdmin('/admin/documents')
    const table = await screen.findByRole('table', { name: 'Document list' })
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search documents' }), { target: { value: 'failed-report' } })
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'complete' } })
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-08-21' } })
    expect(screen.getByText('No documents match these filters.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-08-19' } })
    expect(screen.getByText('No documents match these filters.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'all' } })
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'oldest' } })
    expect(within(screen.getByRole('table')).getAllByRole('row')[1]).toHaveTextContent('Approved report')
  })

  it('retains audit selection, before/after evidence and chain status across filters', async () => {
    renderAdmin('/admin/audit-log')
    await screen.findByRole('table', { name: 'Audit log entries' })
    fireEvent.change(screen.getByLabelText('Action'), { target: { value: 'edit_metadata' } })
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    expect(within(table).getByText('Linked')).toBeInTheDocument()
    const details = await screen.findByRole('complementary', { name: 'Selected action details' })
    expect(details.closest('tr')).toBeNull()
    expect(within(details).getByText('Old title')).toBeInTheDocument()
    expect(within(details).getByText('Previous value')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Actor'), { target: { value: 'owner@example.com' } })
    expect(screen.getByText('No audit events match these filters.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Action'), { target: { value: 'all' } })
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2)
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-08-21' } })
    expect(screen.getByText('No audit events match these filters.')).toBeInTheDocument()
  })

  it('retains audit search, date limits, sort and broken-chain filtering', async () => {
    vi.mocked(auditService.list).mockResolvedValue([{ ...entries[0], prev_hash: 'tampered' }, ...entries.slice(1)])
    renderAdmin('/admin/audit-log')
    await screen.findByRole('table')
    fireEvent.change(screen.getByLabelText('Chain status'), { target: { value: 'broken' } })
    expect(within(screen.getByRole('table')).getByText('Broken')).toBeInTheDocument()
    expect(screen.getByText('1 of 3 events')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Chain status'), { target: { value: 'all' } })
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search audit log' }), { target: { value: 'owner@example.com' } })
    expect(screen.getByText('1 of 3 events')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'oldest' } })
    expect(within(screen.getByRole('table')).getAllByRole('row')[1]).toHaveTextContent('Uploaded document')
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-08-20' } })
    expect(screen.getByText('1 of 3 events')).toBeInTheDocument()
  })

  it('retains pagination and selects the first entry on each page', async () => {
    const many = Array.from({ length: 55 }, (_, index) => ({ ...entries[0], id: 100 - index }))
    vi.mocked(auditService.list).mockResolvedValue(many)
    renderAdmin('/admin/audit-log')
    expect(await screen.findByText('Page 1 of 2')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(51)
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(6)
    expect(screen.getByRole('complementary', { name: 'Selected action details' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
  })

  it('reports load failures without substituting sample records', async () => {
    vi.mocked(auditService.list).mockRejectedValue(new Error('Unavailable'))
    renderAdmin('/admin/audit-log')
    expect(await screen.findByRole('alert')).toHaveTextContent('audit log could not be loaded')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
