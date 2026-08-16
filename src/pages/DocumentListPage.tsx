import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Check, Minus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AdminModeSwitcher } from '../components/AdminModeSwitcher'
import { ActorChip, PageCountBadge } from '../components/AuditActionDetail'
import { converterStagePath } from '../lib/converterRoutes'
import { auditService, documentService } from '../services'
import type { ProcessingState } from '../types/konverter'

const statusLabels: Record<ProcessingState, string> = {
  idle: 'Queued',
  running: 'Processing',
  complete: 'Ready to review',
  failed: 'Needs retry',
}

function StatusPill({ state }: { state?: ProcessingState }) {
  const resolved = state ?? 'idle'
  return (
    <span className={`document-state-pill state-${resolved}`}>
      <span className="document-state-dot" aria-hidden="true" />
      {statusLabels[resolved]}
    </span>
  )
}

function ApprovedBadge({ approvedAt }: { approvedAt?: string | null }) {
  if (approvedAt) {
    return <span className="conf conf--high"><Check className="ic" aria-hidden="true" />Approved</span>
  }
  return <span className="conf conf--neutral"><Minus className="ic" aria-hidden="true" />Not yet</span>
}

export function DocumentListPage() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | ProcessingState>('all')
  const { data: documents = [], isLoading, isError } = useQuery({
    queryKey: ['documents', 'all'],
    queryFn: () => documentService.listAllDocuments(),
  })
  const { data: auditEntries = [] } = useQuery({
    queryKey: ['audit-log'],
    queryFn: () => auditService.list(),
  })

  const visibleDocuments = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('en-AU')
    return documents.filter((document) => (
      (statusFilter === 'all' || (document.processingState ?? 'idle') === statusFilter)
      && (!query || [document.title, document.fileName, document.uploadedByEmail]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase('en-AU')
        .includes(query))
    ))
  }, [documents, search, statusFilter])

  const hasFilters = Boolean(search) || statusFilter !== 'all'

  return (
    <section className="screen active" aria-labelledby="doc-list-heading">
      <div className="admin-page-header">
        <Link className="btn btn-ghost btn-sm" to={converterStagePath('upload')} aria-label="Back to converter">
          <ArrowLeft aria-hidden="true" />
        </Link>
        <div>
          <span className="eyebrow">Admin only</span>
          <h2 id="doc-list-heading">Doc list</h2>
          <p className="lead">Every document uploaded by every user, regardless of ownership.</p>
        </div>
      </div>

      <AdminModeSwitcher documentCount={documents.length} auditCount={auditEntries.length} />

      {isLoading ? (
        <div className="panel panel-pad">
          <div className="page-loading" role="status">Loading documents…</div>
        </div>
      ) : isError ? (
        <div className="panel panel-pad">
          <div className="banner banner-err" role="alert">The document list could not be loaded.</div>
        </div>
      ) : (
        <>
          <div className="admin-toolbar">
            <input
              className="input"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by title, file name, or uploader"
              aria-label="Search documents"
            />
            <label className="tb-control">
              <span className="sr-only">Status</span>
              <select
                className="sel"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as 'all' | ProcessingState)}
              >
                <option value="all">All statuses</option>
                <option value="idle">Queued</option>
                <option value="running">Processing</option>
                <option value="complete">Ready to review</option>
                <option value="failed">Needs retry</option>
              </select>
            </label>
            <span className="admin-count">{visibleDocuments.length} of {documents.length} documents</span>
          </div>

          <div className="panel panel-pad">
            {documents.length === 0 ? (
              <p className="hint">No documents yet.</p>
            ) : visibleDocuments.length === 0 ? (
              <p className="hint">No documents match {hasFilters ? 'these filters' : 'this search'}.</p>
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <caption className="sr-only">Document list</caption>
                  <thead>
                    <tr>
                      <th scope="col">Title</th>
                      <th scope="col">File</th>
                      <th scope="col" className="admin-table-num">Pages</th>
                      <th scope="col">Uploaded by</th>
                      <th scope="col">Status</th>
                      <th scope="col">Approved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleDocuments.map((document) => (
                      <tr key={document.id}>
                        <td>{document.title}</td>
                        <td className="mono">{document.fileName}</td>
                        <td className="admin-table-num"><PageCountBadge pages={document.pages} /></td>
                        <td><ActorChip email={document.uploadedByEmail} /></td>
                        <td><StatusPill state={document.processingState} /></td>
                        <td><ApprovedBadge approvedAt={document.approvedAt} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  )
}
