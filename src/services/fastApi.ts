import { apiRequest } from './httpClient'
import { runtimeConfig } from '../config/runtime'
import type { ApprovalService, AuditListParams, AuditService, DocumentService, MetadataService, PublicationService, ReviewService } from './contracts'
import type {
  DocumentMetadata,
  ReviewUpdate,
  ReviewStatus,
  ReviewTableData,
  ReviewType,
} from '../types/konverter'

function requireDocumentId(documentId?: string): string {
  if (!documentId) throw new Error('Select a document before making this request')
  return encodeURIComponent(documentId)
}

export const fastApiDocumentService: DocumentService = {
  listDocuments() {
    return apiRequest('/documents')
  },
  listAllDocuments() {
    return apiRequest('/documents/all')
  },
  async uploadDocuments(files) {
    const body = new FormData()
    files.forEach((file) => body.append('files', file))
    return apiRequest('/documents', { method: 'POST', body })
  },
  getDocument(documentId) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}`)
  },
  removeDocument(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' })
  },
  startProcessing(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/process`, { method: 'POST' })
  },
  getProcessingStatus(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/processing-state`, {
      method: 'POST',
      cache: 'no-store',
      headers: {
        Accept: 'text/plain',
        'X-Requested-With': 'XMLHttpRequest',
      },
    })
  },
  getProcessingSummary(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/processing-summary`)
  },
  stopProcessing(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/process`, { method: 'DELETE' })
  },
}

export const fastApiReviewService: ReviewService = {
  getReviewItems(documentId) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}/review-items`)
  },
  setStatus(id: string, status: ReviewStatus, documentId?: string) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}/review-items/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    })
  },
  updateText(id: string, text: string, documentId?: string) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}/review-items/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ correctedText: text, status: 'edited' }),
    })
  },
  updateTable(id: string, table: ReviewTableData, documentId?: string) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}/review-items/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ correctedTable: table, status: 'edited' }),
    })
  },
  updateLabel(id: string, type: ReviewType, label: string, documentId?: string) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}/review-items/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ type, label, status: 'edited' }),
    })
  },
  saveItem(id: string, changes: ReviewUpdate, documentId?: string) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}/review-items/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(changes),
    })
  },
  bulkUpdate(ids: string[], changes: ReviewUpdate, documentId?: string) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}/review-items/bulk`, {
      method: 'POST',
      body: JSON.stringify({ itemIds: ids, changes }),
    })
  },
  resolveAll(documentId) {
    return apiRequest(`/documents/${requireDocumentId(documentId)}/review-items/resolve-all`, { method: 'POST' })
  },
}

export const fastApiMetadataService: MetadataService = {
  async save(metadata, documentId) {
    return apiRequest<DocumentMetadata>(`/documents/${requireDocumentId(documentId)}/metadata`, {
      method: 'PUT',
      body: JSON.stringify(metadata),
    })
  },
  get(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/metadata`)
  },
}

export const fastApiApprovalService: ApprovalService = {
  approve(documentId) {
    // Output generation renders every figure in the document, so allow far
    // more time than a normal API call before giving up.
    return apiRequest(`/documents/${requireDocumentId(documentId)}/approval`, {
      method: 'POST',
      timeoutMs: 5 * 60 * 1000,
    })
  },
  revoke(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/approval`, { method: 'DELETE' })
  },
}

function auditQuery(params?: AuditListParams): string {
  if (!params) return ''
  const search = new URLSearchParams()
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  const query = search.toString()
  return query ? `?${query}` : ''
}

export const fastApiAuditService: AuditService = {
  list(params) {
    return apiRequest(`/audit-log${auditQuery(params)}`)
  },
  listMine(params) {
    return apiRequest(`/audit-log/mine${auditQuery(params)}`)
  },
  count() {
    return apiRequest<{ total: number }>('/audit-log/count').then((result) => result.total)
  },
}

const documentUrl = (documentId: string, suffix: string) => (
  `${runtimeConfig.apiBaseUrl}/documents/${encodeURIComponent(documentId)}${suffix}`
)

export const fastApiPublicationService: PublicationService = {
  getHtml(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/exports/accessible.html`, { responseType: 'text' })
  },
  get(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/publication`)
  },
  sourceUrl(documentId, page) {
    return `${documentUrl(documentId, '/source')}${page ? `#page=${page}` : ''}`
  },
  evidenceUrl(documentId, reviewItemId, version) {
    const url = documentUrl(documentId, `/review-items/${encodeURIComponent(reviewItemId)}/evidence.png`)
    return version ? `${url}?v=${encodeURIComponent(version)}` : url
  },
  metadataEvidenceUrl(documentId, fieldName) {
    return documentUrl(documentId, `/metadata/${encodeURIComponent(fieldName)}/evidence.png`)
  },
  figureUrl(documentId, imageKey) {
    return documentUrl(documentId, `/figures/${encodeURIComponent(imageKey)}.png`)
  },
  coverUrl(documentId) {
    return documentUrl(documentId, '/cover')
  },
  exportUrl(documentId, type) {
    const suffix = type === 'html'
      ? '/exports/accessible.html'
      : type === 'jsonld'
        ? '/exports/schema.jsonld'
        : '/exports/structured.json'
    return documentUrl(documentId, suffix)
  },
}
