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
  level: 2 | 3 | 4 | 5
  page?: number
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
  items: Array<{ text: string; marker?: string }>
  page?: number
}

export interface DoclingTableBlock {
  type: 'table'
  id: string
  caption: string
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
  | DoclingTableBlock
  | DoclingFigureBlock
  | DoclingCaptionBlock
  | DoclingFormulaBlock
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
  page?: number
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
