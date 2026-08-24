import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AdminModeSwitcher } from '../components/AdminModeSwitcher'
import { AuditActionDetailPanel, AuditLedgerTable } from '../components/AuditActionDetail'
import { AUDIT_LOG_FETCH_LIMIT, auditActionLabel, auditActionLabels, auditChainStatus, toLocalDateKey, type AuditChainStatus } from '../lib/auditFormatting'
import { converterStagePath } from '../lib/converterRoutes'
import { auditService, documentService } from '../services'

const actionOptions = Object.keys(auditActionLabels)

const PAGE_SIZE = 50

type SortOrder = 'newest' | 'oldest'
type ChainFilter = 'all' | AuditChainStatus

const chainFilterLabels: Record<ChainFilter, string> = {
  all: 'All chain states',
  linked: 'Linked',
  unverifiable: 'Unverifiable',
  broken: 'Broken (tampered)',
}

export function AuditLogPage() {
  const [search, setSearch] = useState('')
  const [actionFilter, setActionFilter] = useState('all')
  const [actorFilter, setActorFilter] = useState('all')
  const [chainFilter, setChainFilter] = useState<ChainFilter>('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sortOrder, setSortOrder] = useState<SortOrder>('newest')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [page, setPage] = useState(0)

  const { data: entries = [], isLoading, isError } = useQuery({
    queryKey: ['audit-log', AUDIT_LOG_FETCH_LIMIT],
    queryFn: () => auditService.list({ limit: AUDIT_LOG_FETCH_LIMIT }),
  })
  const { data: documents = [] } = useQuery({
    queryKey: ['documents', 'all'],
    queryFn: () => documentService.listAllDocuments(),
  })

  const actorOptions = useMemo(() => {
    const emails = new Set<string>()
    entries.forEach((entry) => {
      if (entry.actor_email) emails.add(entry.actor_email)
    })
    return Array.from(emails).sort((a, b) => a.localeCompare(b))
  }, [entries])

  const visibleEntries = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('en-AU')
    const filtered = entries.filter((entry, index) => (
      (actionFilter === 'all' || entry.action === actionFilter)
      && (actorFilter === 'all' || entry.actor_email === actorFilter)
      && (chainFilter === 'all' || auditChainStatus(entries, index) === chainFilter)
      && (!dateFrom || toLocalDateKey(entry.created_at) >= dateFrom)
      && (!dateTo || toLocalDateKey(entry.created_at) <= dateTo)
      && (!query || [entry.actor_email, entry.document_id, auditActionLabel(entry.action)]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase('en-AU')
        .includes(query))
    ))
    return sortOrder === 'oldest' ? [...filtered].reverse() : filtered
  }, [entries, search, actionFilter, actorFilter, chainFilter, dateFrom, dateTo, sortOrder])

  const pageCount = Math.max(1, Math.ceil(visibleEntries.length / PAGE_SIZE))

  useEffect(() => {
    setPage(0)
  }, [search, actionFilter, actorFilter, chainFilter, dateFrom, dateTo, sortOrder])

  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1)
  }, [page, pageCount])

  const pagedEntries = useMemo(
    () => visibleEntries.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE),
    [visibleEntries, page],
  )

  useEffect(() => {
    if (selectedId && pagedEntries.some((entry) => entry.id === selectedId)) return
    setSelectedId(pagedEntries[0]?.id ?? null)
  }, [selectedId, pagedEntries])

  const selectedEntry = pagedEntries.find((entry) => entry.id === selectedId) ?? null
  const selectedDocument = selectedEntry ? documents.find((document) => document.id === selectedEntry.document_id) : undefined
  const hasFilters = Boolean(search) || actionFilter !== 'all' || actorFilter !== 'all' || chainFilter !== 'all' || Boolean(dateFrom) || Boolean(dateTo)

  return (
    <section className="screen active" aria-labelledby="audit-log-heading">
      <div className="admin-page-header">
        <Link className="btn btn-ghost btn-sm" to={converterStagePath('upload')} aria-label="Back to converter">
          <ArrowLeft aria-hidden="true" />
        </Link>
        <div>
          <span className="eyebrow">Admin only</span>
          <h2 id="audit-log-heading">Audit log</h2>
          <p className="lead">Permanent, tamper-evident record of every action taken in the workspace.</p>
        </div>
      </div>

      <AdminModeSwitcher documentCount={documents.length} auditCount={entries.length} />

      {isLoading ? (
        <div className="panel panel-pad">
          <div className="page-loading" role="status">Loading audit log…</div>
        </div>
      ) : isError ? (
        <div className="panel panel-pad">
          <div className="banner banner-err" role="alert">The audit log could not be loaded.</div>
        </div>
      ) : (
        <>
          <div className="admin-toolbar">
            <input
              className="input"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by actor, document, or action"
              aria-label="Search audit log"
            />
            <label className="tb-control">
              <span className="sr-only">Action</span>
              <select className="sel" value={actionFilter} onChange={(event) => setActionFilter(event.target.value)}>
                <option value="all">All actions</option>
                {actionOptions.map((action) => (
                  <option key={action} value={action}>{auditActionLabel(action)}</option>
                ))}
              </select>
            </label>
            <label className="tb-control">
              <span className="sr-only">Actor</span>
              <select className="sel" value={actorFilter} onChange={(event) => setActorFilter(event.target.value)}>
                <option value="all">All actors</option>
                {actorOptions.map((email) => (
                  <option key={email} value={email}>{email}</option>
                ))}
              </select>
            </label>
            <label className="tb-control">
              <span className="sr-only">Chain status</span>
              <select className="sel" value={chainFilter} onChange={(event) => setChainFilter(event.target.value as ChainFilter)}>
                {(Object.keys(chainFilterLabels) as ChainFilter[]).map((value) => (
                  <option key={value} value={value}>{chainFilterLabels[value]}</option>
                ))}
              </select>
            </label>
            <label className="tb-control">
              <span className="sr-only">Sort</span>
              <select className="sel" value={sortOrder} onChange={(event) => setSortOrder(event.target.value as SortOrder)}>
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
              </select>
            </label>
            <span className="admin-count">{visibleEntries.length} of {entries.length} events</span>
          </div>
          <div className="admin-toolbar">
            <div className="tb-control">
              <label htmlFor="audit-log-date-from">From</label>
              <input
                id="audit-log-date-from"
                className="input"
                type="date"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </div>
            <div className="tb-control">
              <label htmlFor="audit-log-date-to">To</label>
              <input
                id="audit-log-date-to"
                className="input"
                type="date"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={(event) => setDateTo(event.target.value)}
              />
            </div>
          </div>

          {entries.length === 0 ? (
            <div className="panel panel-pad">
              <p className="hint">No audit events yet.</p>
            </div>
          ) : visibleEntries.length === 0 ? (
            <div className="panel panel-pad">
              <p className="hint">No audit events match {hasFilters ? 'these filters' : 'this search'}.</p>
            </div>
          ) : (
            <>
              <div className="audit-ledger-workspace">
                <div className="audit-ledger-panel">
                  <AuditLedgerTable
                    entries={pagedEntries}
                    selectedId={selectedId}
                    onSelect={setSelectedId}
                    showActor
                    getChainStatus={(entry) => auditChainStatus(entries, entries.indexOf(entry))}
                    caption="Audit log entries"
                  />
                </div>
                {selectedEntry ? (
                  <AuditActionDetailPanel
                    entry={selectedEntry}
                    documentTitle={selectedDocument?.title ?? null}
                    documentFileName={selectedDocument?.fileName ?? null}
                    showActor
                  />
                ) : null}
              </div>
              {pageCount > 1 ? (
                <div className="admin-pager">
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    onClick={() => setPage((current) => Math.max(0, current - 1))}
                    disabled={page === 0}
                  >
                    Previous
                  </button>
                  <span>Page {page + 1} of {pageCount}</span>
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
                    disabled={page >= pageCount - 1}
                  >
                    Next
                  </button>
                </div>
              ) : null}
            </>
          )}
        </>
      )}
    </section>
  )
}
