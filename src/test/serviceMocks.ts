import type {
  ApprovalService,
  DocumentService,
  MetadataService,
  PublicationService,
  ReviewService,
} from '../services/contracts'
import type {
  DocumentMetadata,
  DocumentSummary,
  ReviewStatus,
  ReviewTableData,
  ReviewType,
  ReviewUpdate,
} from '../types/konverter'
import {
  testDocument,
  testMetadataPayload,
  testPublicationPayload,
  testReviewItems,
} from './fixtures'

let documents = new Map<string, DocumentSummary>([[testDocument.id, structuredClone(testDocument)]])
let reviewItems = structuredClone(testReviewItems)
let metadataPayload = structuredClone(testMetadataPayload)

export function resetTestServices(): void {
  documents = new Map([[testDocument.id, structuredClone(testDocument)]])
  reviewItems = structuredClone(testReviewItems)
  metadataPayload = structuredClone(testMetadataPayload)
}

export const documentService: DocumentService = {
  // Tests always start from an empty client-side queue.
  async listDocuments() {
    return []
  },
  async uploadDocuments(files) {
    const uploaded = files.map((file, index) => ({
      id: `${file.name}-${file.lastModified}-${index}`,
      title: file.name.replace(/\.pdf$/i, '').replace(/[-_]+/g, ' '),
      fileName: file.name,
      pages: 12,
      publisher: 'Pending metadata extraction',
      sizeLabel: `${Math.max(0.1, file.size / (1024 * 1024)).toFixed(1)} MB`,
      processingState: 'idle' as const,
    }))
    uploaded.forEach((document) => documents.set(document.id, structuredClone(document)))
    return uploaded
  },
  async getDocument(documentId) {
    const document = documentId ? documents.get(documentId) : undefined
    if (!document) throw new Error('Document not found')
    return { ...structuredClone(document), processingState: 'complete' }
  },
  async removeDocument(documentId) {
    documents.delete(documentId)
  },
  async startProcessing(documentId) {
    const document = documents.get(documentId)
    if (document) documents.set(documentId, { ...document, processingState: 'complete' })
    return {
      state: 'complete',
      startedAt: Date.now(),
      durationMs: 10,
      currentStep: 8,
      progress: 100,
      remainingSeconds: 0,
      message: 'Ready for review',
    }
  },
  async getProcessingStatus() {
    return {
      state: 'complete',
      startedAt: Date.now(),
      durationMs: 10,
      currentStep: 8,
      progress: 100,
      remainingSeconds: 0,
      message: 'Ready for review',
    }
  },
  async getProcessingSummary() {
    return {
      pages: { detected: testDocument.pages, total: testDocument.pages, needsReview: 0 },
      headings: { detected: 2, total: 3, needsReview: 1 },
      images: { detected: 0, total: 0, needsReview: 0 },
      tables: { detected: 0, total: 1, needsReview: 1 },
    }
  },
  async stopProcessing() {
    return {
      state: 'idle',
      startedAt: null,
      durationMs: 0,
      currentStep: 0,
      progress: 0,
      remainingSeconds: 0,
    }
  },
}

function findReviewItem(id: string) {
  const item = reviewItems.find((entry) => entry.id === id)
  if (!item) throw new Error('Review item not found')
  return item
}

export const reviewService: ReviewService = {
  async getReviewItems() {
    return structuredClone(reviewItems)
  },
  async setStatus(id: string, status: ReviewStatus) {
    const item = findReviewItem(id)
    item.status = status
    return structuredClone(item)
  },
  async updateText(id: string, text: string) {
    return this.saveItem(id, { correctedText: text, status: 'edited' })
  },
  async updateTable(id: string, table: ReviewTableData) {
    return this.saveItem(id, { correctedTable: table, status: 'edited' })
  },
  async updateLabel(id: string, type: ReviewType, label: string) {
    return this.saveItem(id, { type, label, status: 'edited' })
  },
  async saveItem(id: string, changes: ReviewUpdate) {
    const item = findReviewItem(id)
    if (changes.type) {
      item.type = changes.type
      item.label = changes.label ?? changes.type
      item.kind = changes.type === 'table' || changes.type === 'document_index' ? 'table' : 'text'
      if (item.kind === 'text' && item.tableData && changes.correctedText === undefined) {
        item.correctedText = item.tableData.rows
          .map((row) => row.filter(Boolean).join(' — '))
          .join('\n')
      }
    }
    if (changes.correctedText !== undefined) item.correctedText = changes.correctedText
    if (changes.correctedTable !== undefined) item.correctedTable = structuredClone(changes.correctedTable)
    item.status = changes.status ?? 'edited'
    return structuredClone(item)
  },
  async bulkUpdate(ids: string[], changes: ReviewUpdate) {
    const updated = []
    for (const id of ids) updated.push(await this.saveItem(id, changes))
    return structuredClone(updated)
  },
  async resolveAll() {
    reviewItems = reviewItems.map((item) => (
      item.status === 'pending' || item.status === 'needs_attention'
        ? { ...item, status: 'accepted' as const }
        : item
    ))
    return structuredClone(reviewItems)
  },
}

export const metadataService: MetadataService = {
  async save(metadata: DocumentMetadata) {
    metadataPayload.metadata = structuredClone(metadata)
    return structuredClone(metadata)
  },
  async get() {
    return structuredClone(metadataPayload)
  },
}

export const approvalService: ApprovalService = {
  async approve() {
    return { approvedAt: '2026-07-30T12:00:00Z' }
  },
  async revoke() {},
}

const documentUrl = (documentId: string, suffix: string) => `/api/documents/${documentId}${suffix}`

export const publicationService: PublicationService = {
  async get() {
    return structuredClone(testPublicationPayload)
  },
  sourceUrl(documentId, page) {
    return `${documentUrl(documentId, '/source')}${page ? `#page=${page}` : ''}`
  },
  evidenceUrl(documentId, reviewItemId, version) {
    const url = documentUrl(documentId, `/review-items/${reviewItemId}/evidence.png`)
    return version ? `${url}?v=${encodeURIComponent(version)}` : url
  },
  metadataEvidenceUrl(documentId, fieldName) {
    return documentUrl(documentId, `/metadata/${fieldName}/evidence.png`)
  },
  figureUrl(documentId, imageKey) {
    return documentUrl(documentId, `/figures/${imageKey}.png`)
  },
  coverUrl(documentId) {
    return documentUrl(documentId, '/cover')
  },
  exportUrl(documentId, type) {
    return documentUrl(documentId, `/exports/${type}`)
  },
}
