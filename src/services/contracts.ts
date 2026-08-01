import type {
  DocumentMetadata,
  DocumentProcessingJob,
  DocumentSummary,
  MetadataPayload,
  PublicationPayload,
  ReviewItem,
  ReviewUpdate,
  ReviewStatus,
  ReviewTableData,
  ReviewType,
} from '../types/konverter'

export interface DocumentService {
  uploadDocuments(files: File[]): Promise<DocumentSummary[]>
  listDocuments(): Promise<DocumentSummary[]>
  getDocument(documentId?: string): Promise<DocumentSummary>
  removeDocument(documentId: string): Promise<void>
  startProcessing(documentId: string): Promise<DocumentProcessingJob>
  getProcessingStatus(documentId: string): Promise<DocumentProcessingJob>
  stopProcessing(documentId: string): Promise<DocumentProcessingJob>
}

export interface ReviewService {
  getReviewItems(documentId?: string): Promise<ReviewItem[]>
  setStatus(id: string, status: ReviewStatus, documentId?: string): Promise<ReviewItem>
  updateText(id: string, text: string, documentId?: string): Promise<ReviewItem>
  updateTable(id: string, table: ReviewTableData, documentId?: string): Promise<ReviewItem>
  updateLabel(id: string, type: ReviewType, label: string, documentId?: string): Promise<ReviewItem>
  saveItem(id: string, changes: ReviewUpdate, documentId?: string): Promise<ReviewItem>
  resolveAll(documentId?: string): Promise<ReviewItem[]>
}

export interface MetadataService {
  save(metadata: DocumentMetadata, documentId?: string): Promise<DocumentMetadata>
  get(documentId: string): Promise<MetadataPayload>
}

export interface ApprovalService {
  approve(documentId?: string): Promise<{ approvedAt: string }>
  revoke(documentId: string): Promise<void>
}

export interface PublicationService {
  get(documentId: string): Promise<PublicationPayload>
  sourceUrl(documentId: string, page?: number): string
  evidenceUrl(documentId: string, reviewItemId: string): string
  metadataEvidenceUrl(documentId: string, fieldName: string): string
  figureUrl(documentId: string, imageKey: string): string
  coverUrl(documentId: string): string
  exportUrl(documentId: string, type: 'html' | 'jsonld' | 'structured'): string
}
