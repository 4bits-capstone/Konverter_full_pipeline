import type { AuditLogEntry } from '../types/konverter'

export const auditActionLabels: Record<string, string> = {
  upload: 'Uploaded document',
  delete_document: 'Deleted document',
  process_start: 'Started processing',
  process_stop: 'Stopped processing',
  process_failed: 'Processing failed',
  edit_review_item: 'Edited review item',
  edit_metadata: 'Edited metadata',
  approve: 'Approved document',
  revoke_approval: 'Revoked approval',
}

export function auditActionLabel(action: string): string {
  return auditActionLabels[action] ?? action
}

export type AuditActionTone = 'high' | 'med' | 'low' | 'info' | 'neutral'

const auditActionTones: Record<string, AuditActionTone> = {
  upload: 'info',
  delete_document: 'low',
  process_start: 'info',
  process_stop: 'neutral',
  process_failed: 'low',
  edit_review_item: 'med',
  edit_metadata: 'med',
  approve: 'high',
  revoke_approval: 'med',
}

export function auditActionTone(action: string): AuditActionTone {
  return auditActionTones[action] ?? 'neutral'
}

/** One short, human-readable line per entry for the ledger table — e.g. the
 * file name for an upload, not the raw "pages: 519, file_name: …" dump. The
 * full breakdown is still available by clicking through to the detail panel,
 * so this only needs to carry the single most useful fact for scanning the
 * list at a glance. */
export function auditEntrySummary(entry: AuditLogEntry): string {
  const detail = entry.detail ?? {}
  switch (entry.action) {
    case 'upload':
    case 'delete_document':
    case 'process_start':
    case 'process_stop':
    case 'approve':
    case 'revoke_approval':
      return typeof detail.file_name === 'string' ? detail.file_name : '—'
    case 'edit_metadata':
      return typeof detail.title === 'string' ? `Title: ${detail.title}` : '—'
    case 'edit_review_item':
      if (Array.isArray(detail.item_ids)) return `${detail.item_ids.length} items`
      if (detail.resolve_all) return `${typeof detail.count === 'number' ? detail.count : 'all'} items resolved`
      if (typeof detail.item_id === 'string') return '1 item'
      return '—'
    case 'process_failed':
      if (typeof detail.file_name === 'string' && typeof detail.error === 'string') {
        return `${detail.file_name} — ${detail.error}`
      }
      if (typeof detail.file_name === 'string') return detail.file_name
      return typeof detail.error === 'string' ? detail.error : '—'
    default:
      return '—'
  }
}

const auditTimeFormatter = new Intl.DateTimeFormat('en-AU', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

export function formatAuditTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : auditTimeFormatter.format(date)
}

const auditDateOnlyFormatter = new Intl.DateTimeFormat('en-AU', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

const auditTimeOnlyFormatter = new Intl.DateTimeFormat('en-AU', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

export interface AuditDateParts {
  date: string
  time: string
}

/** Splits a timestamp into separate date/time strings for a two-line
 * display, instead of one long mono blob that wraps awkwardly in a table
 * cell. */
export function formatAuditDateParts(value: string): AuditDateParts {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return { date: value, time: '' }
  return {
    date: auditDateOnlyFormatter.format(date),
    time: auditTimeOnlyFormatter.format(date),
  }
}

export type AuditChainStatus = 'linked' | 'unverifiable' | 'broken'

/** Whether this row's prev_hash matches the entry_hash of the row right
 * before it in the chain (entries are newest-first, so "before" is the next
 * array element). Rows written before Layer 4's trigger existed have null
 * hashes and are treated as unverifiable rather than broken. */
export function auditChainStatus(entries: AuditLogEntry[], index: number): AuditChainStatus {
  const entry = entries[index]
  const previous = entries[index + 1]
  if (!entry.prev_hash || !entry.entry_hash) return 'unverifiable'
  if (!previous) return entry.prev_hash === '0'.repeat(64) ? 'linked' : 'unverifiable'
  if (!previous.entry_hash) return 'unverifiable'
  return entry.prev_hash === previous.entry_hash ? 'linked' : 'broken'
}

export interface UploadedDocumentSummary {
  documentId: string | null
  fileName: string
  pages: number | null
  uploadedAt: string
}

/** Derives "documents this user has uploaded, all-time" from their own
 * upload actions. The audit log is permanent, so this still lists a document
 * even after it's later deleted — a real, immutable upload record. */
export function extractUploadedDocuments(entries: AuditLogEntry[]): UploadedDocumentSummary[] {
  return entries
    .filter((entry) => entry.action === 'upload')
    .map((entry) => {
      const detail = entry.detail ?? {}
      const fileName = typeof detail.file_name === 'string' ? detail.file_name : 'Unknown file'
      const pages = typeof detail.pages === 'number' ? detail.pages : null
      return {
        documentId: entry.document_id,
        fileName,
        pages,
        uploadedAt: entry.created_at,
      }
    })
}
