import {
  CheckCircle2,
  FileUp,
  Pencil,
  Play,
  RotateCcw,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  Square,
  Trash2,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import {
  auditActionLabel,
  auditActionTone,
  auditEntrySummary,
  formatAuditDateParts,
  type AuditActionTone,
  type AuditChainStatus,
} from '../lib/auditFormatting'
import type { AuditLogEntry } from '../types/konverter'

const actionIcons: Record<string, LucideIcon> = {
  upload: FileUp,
  delete_document: Trash2,
  process_start: Play,
  process_stop: Square,
  process_failed: TriangleAlert,
  edit_review_item: Pencil,
  edit_metadata: Pencil,
  approve: CheckCircle2,
  revoke_approval: RotateCcw,
}

function actionIcon(action: string): LucideIcon {
  return actionIcons[action] ?? ScrollText
}

export function ActionBadge({ action }: { action: string }) {
  const Icon = actionIcon(action)
  return (
    <span className={`conf conf--${auditActionTone(action)}`}>
      <Icon className="ic" aria-hidden="true" />{auditActionLabel(action)}
    </span>
  )
}

export function ActorChip({ email }: { email: string | null | undefined }) {
  const resolved = email ?? 'Unknown user'
  return (
    <span className="audit-actor-chip">
      <span className="audit-actor-avatar" aria-hidden="true">{resolved.charAt(0).toUpperCase()}</span>
      {resolved}
    </span>
  )
}

export function PageCountBadge({ pages }: { pages: number | null | undefined }) {
  if (pages == null) return <span className="muted">—</span>
  return <span className="page-count-chip mono">{pages}</span>
}

export function TimeStack({ value }: { value: string }) {
  const { date, time } = formatAuditDateParts(value)
  return (
    <span className="audit-time-stack">
      <strong>{date}</strong>
      <span className="mono">{time}</span>
    </span>
  )
}

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
  const format = (item: unknown) => (typeof item === 'string' ? item : JSON.stringify(item))
  return (
    <>
      {visible.map(format).join(', ')}
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
            <th scope="col">Summary</th>
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
                  <TimeStack value={entry.created_at} />
                </button>
              </td>
              {showActor ? <td><ActorChip email={entry.actor_email} /></td> : null}
              <td><ActionBadge action={entry.action} /></td>
              <td className="audit-summary-cell" title={auditEntrySummary(entry)}>{auditEntrySummary(entry)}</td>
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
  const Icon = actionIcon(entry.action)
  const tone: AuditActionTone = auditActionTone(entry.action)
  return (
    <aside className="audit-detail-panel" aria-label="Selected action details">
      <div className="audit-detail-heading">
        <span className={`audit-detail-icon audit-detail-icon--${tone}`} aria-hidden="true"><Icon /></span>
        <div>
          <span className="audit-detail-kicker">Selected action</span>
          <h3>{auditActionLabel(entry.action)}</h3>
        </div>
      </div>
      <dl className="audit-detail-facts">
        <div>
          <dt>Date and time</dt>
          <dd><TimeStack value={entry.created_at} /></dd>
        </div>
        {showActor ? (
          <div>
            <dt>Actor</dt>
            <dd><ActorChip email={entry.actor_email} /></dd>
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
