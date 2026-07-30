import { apiRequest } from './httpClient'
import { runtimeConfig } from '../config/runtime'
import type { ApprovalService, DocumentService, MetadataService, PublicationService, ReviewService } from './contracts'
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
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/status`)
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
    return apiRequest(`/documents/${requireDocumentId(documentId)}/approval`, { method: 'POST' })
  },
  revoke(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/approval`, { method: 'DELETE' })
  },
}

const documentUrl = (documentId: string, suffix: string) => (
  `${runtimeConfig.apiBaseUrl}/documents/${encodeURIComponent(documentId)}${suffix}`
)

export const fastApiPublicationService: PublicationService = {
  get(documentId) {
    return apiRequest(`/documents/${encodeURIComponent(documentId)}/publication`)
  },
  sourceUrl(documentId, page) {
    return `${documentUrl(documentId, '/source')}${page ? `#page=${page}` : ''}`
  },
  evidenceUrl(documentId, reviewItemId) {
    return documentUrl(documentId, `/review-items/${encodeURIComponent(reviewItemId)}/evidence.png`)
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
