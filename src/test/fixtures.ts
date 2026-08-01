import type {
  DocumentMetadata,
  DocumentSummary,
  MetadataPayload,
  PublicationPayload,
  ReviewItem,
} from '../types/konverter'

export const testDocument: DocumentSummary = {
  id: 'test-document',
  title: 'Accessibility Standards Report',
  fileName: 'accessibility-standards-report.pdf',
  pages: 12,
  publisher: 'Example Commission',
  sizeLabel: '1.2 MB',
  processingState: 'complete',
}

export const testReviewItems: ReviewItem[] = [
  {
    id: 'review-heading',
    blockId: '#/texts/4',
    type: 'section_header_2',
    label: 'H2',
    page: 2,
    confidence: 0.58,
    band: 'low',
    title: 'Section heading needs confirmation',
    kind: 'text',
    status: 'pending',
    extractedText: 'Purpose',
    note: 'Confirm that this heading appears in the chapter outline and body.',
    source: { page: 2, html: '<p class="hl">Purpose</p><span class="page-num">Page 2</span>' },
  },
  {
    id: 'review-table',
    blockId: '#/tables/0',
    type: 'table',
    label: 'Table',
    page: 4,
    confidence: 0.72,
    band: 'med',
    title: 'Definitions table needs confirmation',
    kind: 'table',
    status: 'pending',
    note: 'Confirm that each term remains paired with its definition.',
    tableData: {
      headers: ['Term', 'Definition'],
      rows: [
        ['Accessible format', 'Content that people can perceive and operate.'],
        ['Semantic structure', 'Meaning conveyed through programmatic markup.'],
        ['Review flag', 'An item that requires human confirmation.'],
      ],
    },
    source: { page: 4, html: '<p class="hl">Definitions</p><span class="page-num">Page 4</span>' },
  },
]

export const testMetadata: DocumentMetadata = {
  title: 'Accessibility Standards Report',
  publisher: 'Example Commission',
  publishedDate: '18 June 2026',
  jurisdiction: 'Victoria, Australia',
  citations: 'Example Commission, Accessibility Standards Report (2026)',
}

export const testMetadataPayload: MetadataPayload = {
  metadata: testMetadata,
  fields: {
    title: { band: 'high', score: 0.97, page: 1, evidence: 'Found on page 1.', source: 'Page 1' },
    publisher: { band: 'high', score: 0.94, page: 1, evidence: 'Found on page 1.', source: 'Page 1' },
    publishedDate: { band: 'low', score: 0.41, page: 1, evidence: 'Date needs confirmation.', source: 'Docling text · pages 1–8' },
    jurisdiction: { band: 'med', score: 0.72, page: 1, evidence: 'Jurisdiction needs confirmation.', source: 'Docling text · pages 1–8' },
    citations: { band: 'med', score: 0.68, page: 2, evidence: 'Citation needs confirmation.', source: 'Docling text · pages 1–8' },
  },
}

export const testPublicationPayload: PublicationPayload = {
  metadata: testMetadata,
  jsonLd: {
    '@context': 'https://schema.org',
    '@graph': [
      { '@type': 'Report', '@id': 'urn:uuid:test-document', name: testMetadata.title },
      { '@type': 'WebPage', '@id': '#webpage', mainEntity: { '@id': 'urn:uuid:test-document' } },
    ],
  },
  publication: {
    schemaName: 'Konverter accessible document',
    schemaVersion: '1.0',
    sourceName: 'accessibility-standards-report',
    sourceFile: testDocument.fileName,
    summary: ['This report explains practical requirements for producing accessible digital documents.'],
    sections: [
      {
        id: 'introduction',
        title: '1. Introduction',
        displayTitle: '1. Introduction',
        page: 2,
        headings: [
          { type: 'heading', id: 'purpose', text: 'Purpose', level: 2, page: 2 },
          { type: 'heading', id: 'background', text: 'Background', level: 3, page: 3 },
        ],
        blocks: [
          { type: 'heading', id: 'purpose', text: 'Purpose', level: 2, page: 2 },
          { type: 'paragraph', text: 'The report defines a review workflow for accessible documents.', page: 2 },
          { type: 'paragraph', number: '1.2', text: 'Every flagged structure requires human confirmation.', page: 2 },
          { type: 'heading', id: 'background', text: 'Background', level: 3, page: 3 },
          { type: 'paragraph', text: 'The workflow combines extraction, review and accessible publishing.', page: 3 },
        ],
        footnotes: [],
      },
      {
        id: 'requirements',
        title: '2. Requirements',
        displayTitle: '2. Requirements',
        page: 5,
        headings: [
          { type: 'heading', id: 'semantic-output', text: 'Semantic output', level: 2, page: 5 },
        ],
        blocks: [
          { type: 'heading', id: 'semantic-output', text: 'Semantic output', level: 2, page: 5 },
          { type: 'paragraph', text: 'Headings, lists and tables must retain their intended meaning.', page: 5 },
        ],
        footnotes: [],
      },
    ],
    stats: {
      pages: 12,
      textItems: 84,
      tables: 1,
      pictures: 0,
      footnotes: 0,
    },
  },
}
