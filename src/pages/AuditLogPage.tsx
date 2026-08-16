import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AdminModeSwitcher } from '../components/AdminModeSwitcher'
import { AuditActionDetailPanel, AuditLedgerTable } from '../components/AuditActionDetail'
import { auditActionLabel, auditActionLabels, auditChainStatus, type AuditChainStatus } from '../lib/auditFormatting'
import { converterStagePath } from '../lib/converterRoutes'
import { auditService, documentService } from '../services'

const actionOptions = Object.keys(auditActionLabels)

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
  const [sortOrder, setSortOrder] = useState<SortOrder>('newest')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: entries = [], isLoading, isError } = useQuery({
    queryKey: ['audit-log'],
    queryFn: () => auditService.list(),
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
      && (!query || [entry.actor_email, entry.document_id, auditActionLabel(entry.action)]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase('en-AU')
        .includes(query))
    ))
    return sortOrder === 'oldest' ? [...filtered].reverse() : filtered
  }, [entries, search, actionFilter, actorFilter, chainFilter, sortOrder])

  useEffect(() => {
    if (selectedId && visibleEntries.some((entry) => entry.id === selectedId)) return
    setSelectedId(visibleEntries[0]?.id ?? null)
  }, [selectedId, visibleEntries])

  const selectedEntry = visibleEntries.find((entry) => entry.id === selectedId) ?? null
  const selectedDocument = selectedEntry ? documents.find((document) => document.id === selectedEntry.document_id) : undefined
  const hasFilters = Boolean(search) || actionFilter !== 'all' || actorFilter !== 'all' || chainFilter !== 'all'

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

          {entries.length === 0 ? (
            <div className="panel panel-pad">
              <p className="hint">No audit events yet.</p>
            </div>
          ) : visibleEntries.length === 0 ? (
            <div className="panel panel-pad">
              <p className="hint">No audit events match {hasFilters ? 'these filters' : 'this search'}.</p>
            </div>
          ) : (
            <div className="audit-ledger-workspace">
              <div className="audit-ledger-panel">
                <AuditLedgerTable
                  entries={visibleEntries}
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
          )}
        </>
      )}
    </section>
  )
}
