import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Files, ScrollText } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { auditActionLabel, extractUploadedDocuments, formatAuditDetail, formatAuditTime } from '../lib/auditFormatting'
import { converterStagePath } from '../lib/converterRoutes'
import { auditService } from '../services'
import { useKonverter } from '../state/KonverterContext'
import type { AuditLogEntry } from '../types/konverter'

type HistoryView = 'documents' | 'actions'

const ARRAY_PREVIEW_COUNT = 8

function DetailArrayValue({ items }: { items: unknown[] }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = items.length > ARRAY_PREVIEW_COUNT
  const visible = expanded ? items : items.slice(0, ARRAY_PREVIEW_COUNT)
  return (
    <>
      {visible.map((item) => JSON.stringify(item)).join(', ')}
      {isLong ? (
        <>
          {!expanded ? ` and ${items.length - ARRAY_PREVIEW_COUNT} more` : null}{' '}
          <button
            type="button"
            className="audit-detail-seemore"
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? 'Show less' : 'See more'}
          </button>
        </>
      ) : null}
    </>
  )
}

function ActionDetailPanel({ entry, documentTitle, documentFileName }: {
  entry: AuditLogEntry
  documentTitle: string | null
  documentFileName: string | null
}) {
  const details = entry.detail ? Object.entries(entry.detail) : []
  return (
    <aside className="audit-detail-panel" aria-label="Selected action details">
      <div className="audit-detail-heading">
        <span className="audit-detail-icon" aria-hidden="true"><ScrollText /></span>
        <div>
          <span className="audit-detail-kicker">Selected action</span>
          <h3>{auditActionLabel(entry.action)}</h3>
        </div>
      </div>
      <dl className="audit-detail-facts">
        <div>
          <dt>Date and time</dt>
          <dd><time dateTime={entry.created_at}>{formatAuditTime(entry.created_at)}</time></dd>
        </div>
        {entry.document_id ? (
          <div>
            <dt>Document</dt>
            <dd>
              <strong>{documentTitle ?? 'Not currently loaded'}</strong>
              <small className="mono">{documentFileName ?? entry.document_id}</small>
            </dd>
          </div>
        ) : null}
      </dl>
      {details.length > 0 ? (
        <div className="audit-detail-description">
          <span>What happened</span>
          {details.map(([key, value]) => (
            <p key={key}>
              <strong>{key}:</strong>{' '}
              {Array.isArray(value) ? <DetailArrayValue items={value} /> : JSON.stringify(value)}
            </p>
          ))}
        </div>
      ) : null}
    </aside>
  )
}

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
            <div className="audit-ledger-table-wrap">
              <table className="audit-ledger-table">
                <caption className="sr-only">Your actions</caption>
                <thead>
                  <tr>
                    <th scope="col">Time</th>
                    <th scope="col">Action</th>
                    <th scope="col">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => (
                    <tr
                      key={entry.id}
                      className={`audit-ledger-record${selectedAction?.id === entry.id ? ' is-selected' : ''}`}
                      onClick={() => setSelectedActionId(entry.id)}
                    >
                      <td>
                        <button
                          className="audit-ledger-select"
                          type="button"
                          aria-current={selectedAction?.id === entry.id ? 'true' : undefined}
                          onClick={(event) => {
                            event.stopPropagation()
                            setSelectedActionId(entry.id)
                          }}
                        >
                          <time className="mono" dateTime={entry.created_at}>{formatAuditTime(entry.created_at)}</time>
                        </button>
                      </td>
                      <td>{auditActionLabel(entry.action)}</td>
                      <td className="admin-table-detail">{formatAuditDetail(entry.detail)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          {selectedAction ? (
            <ActionDetailPanel
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
