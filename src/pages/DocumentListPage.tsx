import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Check, ChevronDown, FileText, FolderOpen, Minus, X } from 'lucide-react'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AdminModeSwitcher } from '../components/AdminModeSwitcher'
import { ActorChip, PageCountBadge, TimeStack } from '../components/AuditActionDetail'
import { converterStagePath } from '../lib/converterRoutes'
import { AUDIT_LOG_FETCH_LIMIT, toLocalDateKey } from '../lib/auditFormatting'
import { auditService, documentService } from '../services'
import { useKonverter } from '../state/KonverterContext'
import type { DocumentSummary, ProcessingState } from '../types/konverter'

type SortOrder = 'newest' | 'oldest'

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
  const navigate = useNavigate()
  const { reopenDocument } = useKonverter()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | ProcessingState>('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sortOrder, setSortOrder] = useState<SortOrder>('newest')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: documents = [], isLoading, isError } = useQuery({
    queryKey: ['documents', 'all'],
    queryFn: () => documentService.listAllDocuments(),
  })

  // Reopens a processed document at wherever it left off (review, or
  // preview if already approved) without re-uploading or re-processing it.
  const openDocument = (document: DocumentSummary) => {
    const stage = reopenDocument(document)
    navigate(converterStagePath(stage))
  }
  const { data: auditEntries = [] } = useQuery({
    queryKey: ['audit-log', AUDIT_LOG_FETCH_LIMIT],
    queryFn: () => auditService.list({ limit: AUDIT_LOG_FETCH_LIMIT }),
  })

  const visibleDocuments = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('en-AU')
    const filtered = documents.filter((document) => (
      (statusFilter === 'all' || (document.processingState ?? 'idle') === statusFilter)
      && (!dateFrom || (document.uploadedAt && toLocalDateKey(document.uploadedAt) >= dateFrom))
      && (!dateTo || (document.uploadedAt && toLocalDateKey(document.uploadedAt) <= dateTo))
      && (!query || [document.title, document.fileName, document.uploadedByEmail]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase('en-AU')
        .includes(query))
    ))
    return [...filtered].sort((a, b) => {
      const aTime = a.uploadedAt ? new Date(a.uploadedAt).getTime() : 0
      const bTime = b.uploadedAt ? new Date(b.uploadedAt).getTime() : 0
      return sortOrder === 'newest' ? bTime - aTime : aTime - bTime
    })
  }, [documents, search, statusFilter, dateFrom, dateTo, sortOrder])

  useEffect(() => {
    if (!selectedId || visibleDocuments.some((document) => document.id === selectedId)) return
    setSelectedId(null)
  }, [selectedId, visibleDocuments])

  const hasFilters = Boolean(search) || statusFilter !== 'all' || Boolean(dateFrom) || Boolean(dateTo)

  const toggleDetails = (documentId: string) => {
    setSelectedId((current) => current === documentId ? null : documentId)
  }

  const closeDetails = (documentId: string) => {
    setSelectedId(null)
    requestAnimationFrame(() => document.getElementById(`document-detail-trigger-${documentId}`)?.focus())
  }

  return (
    <section className="screen active audit-log-page" aria-labelledby="doc-list-heading">
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
            <label className="tb-control">
              <span className="sr-only">Sort</span>
              <select className="sel" value={sortOrder} onChange={(event) => setSortOrder(event.target.value as SortOrder)}>
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
              </select>
            </label>
            <span className="admin-count">{visibleDocuments.length} of {documents.length} documents</span>
          </div>
          <div className="admin-toolbar">
            <div className="tb-control">
              <label htmlFor="doc-list-date-from">From</label>
              <input
                id="doc-list-date-from"
                className="input"
                type="date"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </div>
            <div className="tb-control">
              <label htmlFor="doc-list-date-to">To</label>
              <input
                id="doc-list-date-to"
                className="input"
                type="date"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={(event) => setDateTo(event.target.value)}
              />
            </div>
          </div>

          {documents.length === 0 ? (
            <div className="panel panel-pad">
              <p className="hint">No documents yet.</p>
            </div>
          ) : visibleDocuments.length === 0 ? (
            <div className="panel panel-pad">
              <p className="hint">No documents match {hasFilters ? 'these filters' : 'this search'}.</p>
            </div>
          ) : (
            <div className="audit-ledger-workspace">
              <div className="audit-ledger-panel">
                <div className="audit-ledger-table-wrap">
                  <table className="audit-ledger-table">
                    <caption className="sr-only">Document list</caption>
                    <thead>
                      <tr>
                        <th scope="col">Title</th>
                        <th scope="col">Uploaded by</th>
                        <th scope="col">Status</th>
                        <th scope="col">Approved</th>
                        <th scope="col"><span className="sr-only">Open</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleDocuments.map((document) => {
                        const expanded = selectedId === document.id
                        const panelId = `document-detail-${document.id}`
                        const titleId = `${panelId}-title`
                        return (
                          <Fragment key={document.id}>
                            <tr
                              className={`audit-ledger-record${expanded ? ' is-expanded' : ''}`}
                              onClick={() => toggleDetails(document.id)}
                            >
                              <td>
                                <button
                                  className="audit-ledger-select"
                                  type="button"
                                  aria-expanded={expanded}
                                  aria-controls={panelId}
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    toggleDetails(document.id)
                                  }}
                                >
                                  <strong>{document.title}</strong>
                                </button>
                              </td>
                              <td><ActorChip email={document.uploadedByEmail} /></td>
                              <td><StatusPill state={document.processingState} /></td>
                              <td><ApprovedBadge approvedAt={document.approvedAt} /></td>
                              <td className="audit-ledger-action-cell">
                                <div className="audit-row-end">
                                  <button
                                    className="btn btn-outline btn-sm"
                                    type="button"
                                    disabled={document.processingState !== 'complete'}
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      openDocument(document)
                                    }}
                                  >
                                    Open
                                  </button>
                                  <button
                                    id={`document-detail-trigger-${document.id}`}
                                    className="audit-disclosure-button"
                                    type="button"
                                    aria-label={`${expanded ? 'Hide' : 'Show'} document details: ${document.title}`}
                                    aria-expanded={expanded}
                                    aria-controls={panelId}
                                    title={expanded ? 'Hide details' : 'Show details'}
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      toggleDetails(document.id)
                                    }}
                                  >
                                    <ChevronDown aria-hidden="true" />
                                  </button>
                                </div>
                              </td>
                            </tr>
                            {expanded ? (
                              <tr className="audit-inline-detail-row is-document-detail">
                                <td colSpan={5}>
                                  <aside
                                    className="audit-detail-panel audit-document-detail is-inline"
                                    id={panelId}
                                    tabIndex={-1}
                                    aria-label="Selected document details"
                                  >
                                    <div className="audit-detail-heading">
                                      <span className="audit-detail-icon audit-detail-icon--info" aria-hidden="true"><FileText /></span>
                                      <div>
                                        <span className="audit-detail-kicker">Selected document</span>
                                        <h3 id={titleId}>{document.title}</h3>
                                      </div>
                                      <div className="audit-detail-heading-actions">
                                        <button
                                          className="btn btn-primary btn-sm"
                                          type="button"
                                          disabled={document.processingState !== 'complete'}
                                          onClick={() => openDocument(document)}
                                        >
                                          <FolderOpen aria-hidden="true" />
                                          Open
                                        </button>
                                        <button
                                          className="audit-detail-close"
                                          type="button"
                                          aria-label="Close document details"
                                          onClick={() => closeDetails(document.id)}
                                        >
                                          <X aria-hidden="true" />
                                        </button>
                                      </div>
                                    </div>
                                    <dl className="audit-detail-facts">
                                      <div>
                                        <dt>File</dt>
                                        <dd className="mono">{document.fileName}</dd>
                                      </div>
                                      <div>
                                        <dt>Pages</dt>
                                        <dd><PageCountBadge pages={document.pages} /></dd>
                                      </div>
                                      <div>
                                        <dt>Uploaded by</dt>
                                        <dd><ActorChip email={document.uploadedByEmail} /></dd>
                                      </div>
                                      <div>
                                        <dt>Uploaded</dt>
                                        <dd>
                                          {document.uploadedAt
                                            ? <TimeStack value={document.uploadedAt} />
                                            : <span className="muted">—</span>}
                                        </dd>
                                      </div>
                                      <div>
                                        <dt>Status</dt>
                                        <dd><StatusPill state={document.processingState} /></dd>
                                      </div>
                                      <div>
                                        <dt>Approved</dt>
                                        <dd><ApprovedBadge approvedAt={document.approvedAt} /></dd>
                                      </div>
                                    </dl>
                                  </aside>
                                </td>
                              </tr>
                            ) : null}
                          </Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}
