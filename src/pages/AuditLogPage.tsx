import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AdminModeSwitcher } from '../components/AdminModeSwitcher'
import { AuditActionDetailPanel, AuditLedgerTable } from '../components/AuditActionDetail'
import { auditActionLabel, auditActionLabels, auditChainStatus } from '../lib/auditFormatting'
import { converterStagePath } from '../lib/converterRoutes'
import { auditService, documentService } from '../services'

const actionOptions = Object.keys(auditActionLabels)

export function AuditLogPage() {
  const [search, setSearch] = useState('')
  const [actionFilter, setActionFilter] = useState('all')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: entries = [], isLoading, isError } = useQuery({
    queryKey: ['audit-log'],
    queryFn: () => auditService.list(),
  })
  const { data: documents = [] } = useQuery({
    queryKey: ['documents', 'all'],
    queryFn: () => documentService.listAllDocuments(),
  })

  const visibleEntries = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('en-AU')
    return entries.filter((entry) => (
      (actionFilter === 'all' || entry.action === actionFilter)
      && (!query || [entry.actor_email, entry.document_id, auditActionLabel(entry.action)]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase('en-AU')
        .includes(query))
    ))
  }, [entries, search, actionFilter])

  useEffect(() => {
    if (selectedId && visibleEntries.some((entry) => entry.id === selectedId)) return
    setSelectedId(visibleEntries[0]?.id ?? null)
  }, [selectedId, visibleEntries])

  const selectedEntry = visibleEntries.find((entry) => entry.id === selectedId) ?? null
  const selectedDocument = selectedEntry ? documents.find((document) => document.id === selectedEntry.document_id) : undefined
  const hasFilters = Boolean(search) || actionFilter !== 'all'

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
