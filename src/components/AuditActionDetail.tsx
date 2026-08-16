import { ScrollText, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { auditActionLabel, formatAuditDetail, formatAuditTime, type AuditChainStatus } from '../lib/auditFormatting'
import type { AuditLogEntry } from '../types/konverter'

function ChainBadge({ status }: { status: AuditChainStatus }) {
  if (status === 'linked') {
    return (
      <span className="conf conf--high" title="Hash chain intact">
        <ShieldCheck className="ic" aria-hidden="true" />Linked
      </span>
    )
  }
  if (status === 'broken') {
    return (
      <span className="conf conf--low" title="prev_hash does not match the previous entry">
        <ShieldAlert className="ic" aria-hidden="true" />Broken
      </span>
    )
  }
  return (
    <span className="conf conf--med" title="Written before hash chaining was enabled">
      <ShieldAlert className="ic" aria-hidden="true" />Unverifiable
    </span>
  )
}

const ARRAY_PREVIEW_COUNT = 8

export function DetailArrayValue({ items }: { items: unknown[] }) {
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

export function AuditLedgerTable({ entries, selectedId, onSelect, showActor = false, getChainStatus, caption }: {
  entries: AuditLogEntry[]
  selectedId: number | null
  onSelect: (id: number) => void
  showActor?: boolean
  /** Omit to hide the Chain column. Must be computed against the full,
   * unfiltered entry list — chain links depend on true adjacency, not on
   * whatever subset happens to be visible after filtering. */
  getChainStatus?: (entry: AuditLogEntry) => AuditChainStatus
  caption: string
}) {
  return (
    <div className="audit-ledger-table-wrap">
      <table className="audit-ledger-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            {showActor ? <th scope="col">Actor</th> : null}
            <th scope="col">Action</th>
            <th scope="col">Detail</th>
            {getChainStatus ? <th scope="col">Chain</th> : null}
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={entry.id}
              className={`audit-ledger-record${selectedId === entry.id ? ' is-selected' : ''}`}
              onClick={() => onSelect(entry.id)}
            >
              <td>
                <button
                  className="audit-ledger-select"
                  type="button"
                  aria-current={selectedId === entry.id ? 'true' : undefined}
                  onClick={(event) => {
                    event.stopPropagation()
                    onSelect(entry.id)
                  }}
                >
                  <time className="mono" dateTime={entry.created_at}>{formatAuditTime(entry.created_at)}</time>
                </button>
              </td>
              {showActor ? <td>{entry.actor_email ?? '—'}</td> : null}
              <td>{auditActionLabel(entry.action)}</td>
              <td className="admin-table-detail">{formatAuditDetail(entry.detail)}</td>
              {getChainStatus ? <td><ChainBadge status={getChainStatus(entry)} /></td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function AuditActionDetailPanel({ entry, documentTitle, documentFileName, showActor = false }: {
  entry: AuditLogEntry
  documentTitle: string | null
  documentFileName: string | null
  showActor?: boolean
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
        {showActor ? (
          <div>
            <dt>Actor</dt>
            <dd><strong>{entry.actor_email ?? 'Unknown user'}</strong></dd>
          </div>
        ) : null}
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
