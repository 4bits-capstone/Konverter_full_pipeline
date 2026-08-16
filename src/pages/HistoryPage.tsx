import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Files, ScrollText } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AuditActionDetailPanel, AuditLedgerTable, PageCountBadge, TimeStack } from '../components/AuditActionDetail'
import { auditActionLabel, auditActionLabels, extractUploadedDocuments } from '../lib/auditFormatting'
import { converterStagePath } from '../lib/converterRoutes'
import { auditService } from '../services'
import { useKonverter } from '../state/KonverterContext'

type HistoryView = 'documents' | 'actions'

const actionOptions = Object.keys(auditActionLabels)

export function HistoryPage() {
  const [view, setView] = useState<HistoryView>('documents')
  const [search, setSearch] = useState('')
  const [actionFilter, setActionFilter] = useState('all')
  const [selectedActionId, setSelectedActionId] = useState<number | null>(null)
  const { documents } = useKonverter()
  const { data: entries = [], isLoading, isError } = useQuery({
    queryKey: ['audit-log', 'mine'],
    queryFn: () => auditService.listMine(),
  })

  const uploads = useMemo(() => extractUploadedDocuments(entries), [entries])
  const visibleEntries = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('en-AU')
    return entries.filter((entry) => (
      (actionFilter === 'all' || entry.action === actionFilter)
      && (!query || auditActionLabel(entry.action).toLocaleLowerCase('en-AU').includes(query))
    ))
  }, [entries, search, actionFilter])
  const hasFilters = Boolean(search) || actionFilter !== 'all'

  useEffect(() => {
    if (selectedActionId && visibleEntries.some((entry) => entry.id === selectedActionId)) return
    setSelectedActionId(visibleEntries[0]?.id ?? null)
  }, [selectedActionId, visibleEntries])

  const selectedAction = visibleEntries.find((entry) => entry.id === selectedActionId) ?? null
  const selectedDocument = selectedAction ? documents.find((document) => document.id === selectedAction.document_id) : undefined

  return (
    <section className="screen active" aria-labelledby="history-heading">
      <div className="admin-page-header">
        <Link className="btn btn-ghost btn-sm" to={converterStagePath('upload')} aria-label="Back to converter">
          <ArrowLeft aria-hidden="true" />
        </Link>
        <div>
          <span className="eyebrow">Your activity</span>
          <h2 id="history-heading">History</h2>
          <p className="lead">Your own actions and uploaded documents in this workspace.</p>
        </div>
      </div>

      <nav className="audit-mode-switcher" aria-label="History views">
        <button
          type="button"
          className={`audit-mode-link${view === 'documents' ? ' is-active' : ''}`}
          aria-current={view === 'documents' ? 'true' : undefined}
          onClick={() => setView('documents')}
        >
          <Files aria-hidden="true" />
          <span><strong>Documents</strong><small>Uploaded by you</small></span>
          <b>{uploads.length}</b>
        </button>
        <button
          type="button"
          className={`audit-mode-link${view === 'actions' ? ' is-active' : ''}`}
          aria-current={view === 'actions' ? 'true' : undefined}
          onClick={() => setView('actions')}
        >
          <ScrollText aria-hidden="true" />
          <span><strong>Actions</strong><small>Your activity</small></span>
          <b>{entries.length}</b>
        </button>
      </nav>

      {isLoading ? (
        <div className="panel panel-pad">
          <div className="page-loading" role="status">Loading history…</div>
        </div>
      ) : isError ? (
        <div className="panel panel-pad">
          <div className="banner banner-err" role="alert">History could not be loaded.</div>
        </div>
      ) : view === 'documents' ? (
        <div className="panel panel-pad">
          {uploads.length === 0 ? (
            <p className="hint">You haven't uploaded any documents yet.</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <caption className="sr-only">Documents you've uploaded</caption>
                <thead>
                  <tr>
                    <th scope="col">File</th>
                    <th scope="col" className="admin-table-num">Pages</th>
                    <th scope="col">Uploaded</th>
                  </tr>
                </thead>
                <tbody>
                  {uploads.map((upload, index) => (
                    <tr key={`${upload.documentId ?? 'unknown'}-${index}`}>
                      <td className="mono">{upload.fileName}</td>
                      <td className="admin-table-num"><PageCountBadge pages={upload.pages} /></td>
                      <td><TimeStack value={upload.uploadedAt} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : entries.length === 0 ? (
        <div className="panel panel-pad">
          <p className="hint">No activity recorded yet.</p>
        </div>
      ) : (
        <>
          <div className="admin-toolbar">
            <input
              className="input"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by action"
              aria-label="Search your actions"
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

          {visibleEntries.length === 0 ? (
            <div className="panel panel-pad">
              <p className="hint">No actions match your filters.</p>
            </div>
          ) : (
            <div className="audit-ledger-workspace">
              <div className="audit-ledger-panel">
                <AuditLedgerTable
                  entries={visibleEntries}
                  selectedId={selectedAction?.id ?? null}
                  onSelect={setSelectedActionId}
                  caption="Your actions"
                />
              </div>
              {selectedAction ? (
                <AuditActionDetailPanel
                  entry={selectedAction}
                  documentTitle={selectedDocument?.title ?? null}
                  documentFileName={selectedDocument?.fileName ?? null}
                />
              ) : null}
            </div>
          )}
        </>
      )}
    </section>
  )
}
