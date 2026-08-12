export interface DoclingTableCell {
  text: string
  rowSpan: number
  colSpan: number
  columnHeader: boolean
  rowHeader: boolean
  startColumn: number
}

export interface DoclingHeadingBlock {
  type: 'heading'
  id: string
  text: string
  level: 1 | 2 | 3 | 4 | 5
  page?: number
  tocSequence?: number
}

export interface DoclingParagraphBlock {
  type: 'paragraph'
  text: string
  number?: string
  page?: number
}

export interface DoclingListBlock {
  type: 'list'
  style: 'unordered' | 'ordered' | 'numbered-paragraphs'
  items: Array<{
    text: string
    marker?: string
    level?: number
    ordered?: boolean
    value?: number
  }>
  start?: number
  page?: number
}

export interface DoclingBoxSectionBlock {
  type: 'box_section'
  id: string
  title: string
  variant: 'case-study' | 'information' | 'recommendations'
  blocks: DoclingBlock[]
  page?: number
}

export interface DoclingTableBlock {
  type: 'table'
  id: string
  caption?: string
  rows: DoclingTableCell[][]
  page?: number
}

export interface DoclingFigureBlock {
  type: 'figure'
  id: string
  caption: string
  page?: number
  sourceBlockId?: string
  imageKey?: string
}

export interface DoclingCaptionBlock {
  type: 'caption'
  text: string
  page?: number
}

export interface DoclingFormulaBlock {
  type: 'formula'
  text: string
  page?: number
}

export interface DoclingFootnoteBlock {
  type: 'footnote'
  id: string
  text: string
  page?: number
}

export interface DoclingCheckboxBlock {
  type: 'checkbox'
  text: string
  checked: boolean
  page?: number
}

export interface DoclingGroupBlock {
  type: 'group'
  label: string
  items: Array<{ text: string; checked?: boolean }>
  page?: number
}

export type DoclingBlock =
  | DoclingHeadingBlock
  | DoclingParagraphBlock
  | DoclingListBlock
  | DoclingBoxSectionBlock
  | DoclingTableBlock
  | DoclingFigureBlock
  | DoclingCaptionBlock
  | DoclingFormulaBlock
  | DoclingFootnoteBlock
  | DoclingCheckboxBlock
  | DoclingGroupBlock

export interface DoclingFootnote {
  id: string
  text: string
  page?: number
}

export interface DoclingSection {
  id: string
  title: string
  displayTitle: string
  isChapter?: boolean
  page?: number
  tocSequence?: number
  blocks: DoclingBlock[]
  headings: DoclingHeadingBlock[]
  footnotes: DoclingFootnote[]
}

export interface DoclingPublication {
  schemaName: string
  schemaVersion: string
  sourceName: string
  sourceFile: string
  summary?: string[]
  sections: DoclingSection[]
  stats: {
    pages: number
    textItems: number
    tables: number
    pictures: number
    footnotes: number
  }
}
