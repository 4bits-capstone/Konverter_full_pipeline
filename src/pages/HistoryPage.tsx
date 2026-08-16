import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Files, ScrollText } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AuditActionDetailPanel, AuditLedgerTable } from '../components/AuditActionDetail'
import { extractUploadedDocuments, formatAuditTime } from '../lib/auditFormatting'
import { converterStagePath } from '../lib/converterRoutes'
import { auditService } from '../services'
import { useKonverter } from '../state/KonverterContext'

type HistoryView = 'documents' | 'actions'

export function HistoryPage() {
  const [view, setView] = useState<HistoryView>('documents')
  const [selectedActionId, setSelectedActionId] = useState<number | null>(null)
  const { documents } = useKonverter()
  const { data: entries = [], isLoading, isError } = useQuery({
    queryKey: ['audit-log', 'mine'],
    queryFn: () => auditService.listMine(),
  })

  const uploads = useMemo(() => extractUploadedDocuments(entries), [entries])
  const selectedAction = entries.find((entry) => entry.id === selectedActionId) ?? entries[0] ?? null
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
                    <th scope="col">Pages</th>
                    <th scope="col">Uploaded</th>
                  </tr>
                </thead>
                <tbody>
                  {uploads.map((upload, index) => (
                    <tr key={`${upload.documentId ?? 'unknown'}-${index}`}>
                      <td className="mono">{upload.fileName}</td>
                      <td>{upload.pages ?? '—'}</td>
                      <td><time className="mono" dateTime={upload.uploadedAt}>{formatAuditTime(upload.uploadedAt)}</time></td>
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
        <div className="audit-ledger-workspace">
          <div className="audit-ledger-panel">
            <AuditLedgerTable
              entries={entries}
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
    </section>
  )
}
