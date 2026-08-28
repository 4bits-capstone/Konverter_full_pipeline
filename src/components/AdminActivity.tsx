import { Fragment } from 'react'
import { ChevronDown } from 'lucide-react'
import { Link } from 'react-router-dom'
import { auditActionLabel, auditChainStatus, formatAuditTime } from '../lib/auditFormatting'
import { converterAuditLogPath } from '../lib/converterRoutes'
import type { AuditLogEntry, DocumentSummary } from '../types/konverter'
import { AuditActionDetailPanel, ChainBadge, TimeStack } from './AuditActionDetail'

export const activityStages = ['upload', 'processing', 'review', 'metadata', 'preview'] as const
export type ActivityStage = typeof activityStages[number]
export const activityStageLabels: Record<ActivityStage, string> = {
  upload: 'Upload', processing: 'Processing', review: 'Review', metadata: 'Metadata', preview: 'Preview',
}
export function activityStage(action: string): ActivityStage | null {
  if (action === 'upload') return 'upload'
  if (action.startsWith('process_')) return 'processing'
  if (action === 'edit_review_item') return 'review'
  if (action === 'edit_metadata') return 'metadata'
  if (action === 'approve' || action === 'revoke_approval') return 'preview'
  return null
}
export function ActivityLabel({ entry, linked = false }: { entry: AuditLogEntry; linked?: boolean }) {
  const stage = activityStage(entry.action)
  return <>
    {stage && <span className={`audit-stage-badge is-${stage}`}>{activityStageLabels[stage]}</span>}
    {linked ? <Link to={`${converterAuditLogPath()}?event=${entry.id}`}>{auditActionLabel(entry.action)}</Link> : <strong>{auditActionLabel(entry.action)}</strong>}
  </>
}
export function ActivityResult({ entry }: { entry: AuditLogEntry }) {
  // The API has no general outcome field. Do not invent success for every event.
  const failed = entry.action === 'process_failed'
  return <span className={`audit-result is-${failed ? 'failed' : 'recorded'}`}>{failed ? 'Failed' : 'Recorded'}</span>
}
export function ActivityDocument({ entry, documents }: { entry: AuditLogEntry; documents: DocumentSummary[] }) {
  const doc = documents.find(document => document.id === entry.document_id)
  const fileName = doc?.fileName ?? (typeof entry.detail?.file_name === 'string' ? entry.detail.file_name : '')
  return <><strong>{(doc?.title ?? fileName) || (entry.document_id ? 'Document unavailable' : 'Workspace')}</strong>{doc?.title && fileName && <small>{fileName}</small>}</>
}
export function AdminActivityTable({ entries, allEntries, documents, selectedId, onSelect }: {
  entries: AuditLogEntry[]
  allEntries: AuditLogEntry[]
  documents: DocumentSummary[]
  selectedId: number | null
  onSelect: (id: number | null) => void
}) {
  return (
    <div className="audit-ledger-table-wrap">
      <table className="audit-ledger-table">
        <caption className="sr-only">Workspace activity records</caption>
        <thead><tr><th scope="col">User</th><th scope="col">Activity</th><th scope="col">Document</th><th scope="col">Result / chain</th><th scope="col">Time and details</th></tr></thead>
        <tbody>{entries.map(entry => {
          const expanded = selectedId === entry.id
          const doc = documents.find(document => document.id === entry.document_id)
          const panelId = `activity-detail-${entry.id}`
          const triggerId = `activity-trigger-${entry.id}`
          const close = () => { onSelect(null); document.getElementById(triggerId)?.focus() }
          return <Fragment key={entry.id}>
            <tr className={`audit-ledger-record${expanded ? ' is-expanded' : ''}`}>
              <td><strong>{entry.actor_email ?? 'Unknown user'}</strong></td>
              <td><ActivityLabel entry={entry} /></td>
              <td><ActivityDocument entry={entry} documents={documents} /></td>
              <td><div className="audit-result-stack"><ActivityResult entry={entry} /><ChainBadge status={auditChainStatus(allEntries, allEntries.indexOf(entry))} /></div></td>
              <td className="audit-ledger-action-cell"><div className="audit-row-end">
                <time dateTime={entry.created_at} title={formatAuditTime(entry.created_at)}><TimeStack value={entry.created_at} /></time>
                <button id={triggerId} type="button" className="audit-disclosure-button" aria-expanded={expanded} aria-controls={panelId}
                  aria-label={`${expanded ? 'Hide' : 'Show'} activity details: ${auditActionLabel(entry.action)}, ${formatAuditTime(entry.created_at)}`}
                  onClick={() => onSelect(expanded ? null : entry.id)}><ChevronDown aria-hidden="true" /></button>
              </div></td>
            </tr>
            {expanded && <tr className="audit-inline-detail-row"><td colSpan={5}>
              <AuditActionDetailPanel entry={entry} documentTitle={doc?.title ?? null} documentFileName={doc?.fileName ?? null} showActor inlineId={panelId} onClose={close} />
            </td></tr>}
          </Fragment>
        })}</tbody>
      </table>
    </div>
  )
}
