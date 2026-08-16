import type { AuditLogEntry } from '../types/konverter'

export const auditActionLabels: Record<string, string> = {
  upload: 'Uploaded document',
  delete_document: 'Deleted document',
  process_start: 'Started processing',
  edit_review_item: 'Edited review item',
  edit_metadata: 'Edited metadata',
  approve: 'Approved document',
  revoke_approval: 'Revoked approval',
}

export function auditActionLabel(action: string): string {
  return auditActionLabels[action] ?? action
}

function formatDetailValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length > 5 ? `[${value.length} items]` : JSON.stringify(value)
  }
  const text = JSON.stringify(value)
  return text.length > 80 ? `${text.slice(0, 80)}…` : text
}

export function formatAuditDetail(detail: AuditLogEntry['detail']): string {
  if (!detail) return '—'
  const entries = Object.entries(detail)
  if (!entries.length) return '—'
  return entries.map(([key, value]) => `${key}: ${formatDetailValue(value)}`).join(', ')
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

/** Whether this row's prev_hash matches the entry_hash of the row right
 * before it in the chain (entries are newest-first, so "before" is the next
 * array element). Rows written before Layer 4's trigger existed have null
 * hashes and are treated as unverifiable rather than broken. */
export function auditChainStatus(entries: AuditLogEntry[], index: number): 'linked' | 'unverifiable' | 'broken' {
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
