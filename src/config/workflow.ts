import type { DocumentMetadata, ProcessingStep } from '../types/konverter'

export const processingSteps: ProcessingStep[] = [
  { id: 'upload', label: 'Uploading' },
  { id: 'prepare', label: 'Preparing document' },
  { id: 'extract', label: 'Extracting content' },
  { id: 'structure', label: 'Detecting document structure' },
  { id: 'metadata', label: 'Extracting metadata' },
  { id: 'confidence', label: 'Scoring confidence' },
  { id: 'review', label: 'Preparing review' },
  { id: 'outputs', label: 'Generating outputs' },
  { id: 'complete', label: 'Complete' },
]

export const emptyMetadata: DocumentMetadata = {
  title: '',
  publisher: '',
  publishedDate: '',
  jurisdiction: '',
  citations: '',
}
