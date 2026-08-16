export type Stage = 'upload' | 'review' | 'metadata' | 'approval' | 'preview'
export type ConfidenceBand = 'high' | 'med' | 'low'
export type ReviewStatus = 'pending' | 'accepted' | 'edited' | 'needs_attention' | 'removed'
export type ReviewType =
  | 'box_section'
  | 'caption'
  | 'document_index'
  | 'footnote'
  | 'footer'
  | 'form'
  | 'formula'
  | 'header'
  | 'list'
  | 'picture'
  | 'section_header_1'
  | 'section_header_2'
  | 'section_header_3'
  | 'section_header_4'
  | 'section_header_5'
  | 'table'
  | 'title'
  | 'text'
  | 'unspecified'

export interface DocumentSummary {
  id: string
  title: string
  fileName: string
  pages: number
  publisher: string
  sizeLabel?: string
  processingState?: ProcessingState
  approvedAt?: string | null
  metadataConfirmed?: boolean
  uploadedByEmail?: string | null
}

export interface SourceEvidence {
  page: number
  html: string
  bounds?: {
    left: number
    top: number
    right: number
    bottom: number
    pageWidth: number
    pageHeight: number
  }
}

export interface ReviewTableData {
  caption?: string
  headers: string[]
  rows: string[][]
}

export interface ReviewItem {
  id: string
  blockId?: string
  type: ReviewType
  label: string
  page: number
  confidence: number
  band: ConfidenceBand
  title: string
  kind: 'kv' | 'text' | 'table'
  status: ReviewStatus
  extractedText?: string
  correctedText?: string
  note?: string
  keyValues?: Array<[string, string]>
  tableData?: ReviewTableData
  correctedTable?: ReviewTableData
  source: SourceEvidence
}

export interface DocumentMetadata {
  title: string
  publisher: string
  publishedDate: string
  jurisdiction: string
  citations: string
}

export interface MetadataFieldInfo {
  band: ConfidenceBand
  score: number
  page: number
  evidence: string
  source: string
}

export interface MetadataPayload {
  metadata: DocumentMetadata
  fields: Record<keyof DocumentMetadata, MetadataFieldInfo>
}

export interface DocumentConfidence {
  score: number | null
  band: ConfidenceBand | null
  source: string
}

export interface PublicationPayload {
  publication: import('../lib/docling').DoclingPublication
  metadata: DocumentMetadata
  jsonLd: Record<string, unknown>
  confidence?: DocumentConfidence | null
}

export interface ReviewUpdate {
  status?: ReviewStatus
  type?: ReviewType
  label?: string
  correctedText?: string
  correctedTable?: ReviewTableData
}

export interface ProcessingStep {
  id: string
  label: string
  detail?: string
}

export type ProcessingState = 'idle' | 'running' | 'failed' | 'complete'

export interface DocumentProcessingJob {
  state: ProcessingState
  startedAt: number | null
  durationMs: number
  currentStep: number
  progress: number
  remainingSeconds: number
  message?: string
}

export interface ProcessingElementCoverage {
  detected: number
  total: number
  needsReview: number
}

export interface ProcessingSummary {
  pages: ProcessingElementCoverage
  headings: ProcessingElementCoverage
  images: ProcessingElementCoverage
  tables: ProcessingElementCoverage
}

/** One row from the backend's immutable Supabase-backed audit_log table. */
export interface AuditLogEntry {
  id: number
  document_id: string | null
  actor_id: string | null
  actor_email: string | null
  action: string
  detail: Record<string, unknown> | null
  prev_hash: string | null
  entry_hash: string | null
  created_at: string
}
