import type { DocumentMetadata, ProcessingStep } from '../types/konverter'

export const processingSteps: ProcessingStep[] = [
  { id: 'upload', label: 'Document uploaded' },
  { id: 'ingest', label: 'Ingesting document', detail: 'Docling extracts text, layout and tables' },
  { id: 'extract', label: 'Extracting content' },
  { id: 'structure', label: 'Detecting structure', detail: 'chapters, sections and footnotes' },
  { id: 'metadata', label: 'Extracting metadata' },
  { id: 'confidence', label: 'Scoring confidence and flagging' },
  { id: 'ready', label: 'Ready for review' },
]

export const emptyMetadata: DocumentMetadata = {
  title: '',
  publisher: '',
  publishedDate: '',
  jurisdiction: '',
  citations: '',
}
