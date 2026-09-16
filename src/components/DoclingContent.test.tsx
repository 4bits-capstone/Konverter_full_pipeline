import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DoclingContent } from './DoclingContent'

describe('DoclingContent Box Sections', () => {
  it('renders detected quotes as a semantic blockquote with preserved paragraphs', () => {
    const { container } = render(
      <DoclingContent
        footnotes={[]}
        blocks={[{ type: 'quote', text: 'Quoted statement.\n\nSpeaker attribution' }]}
      />,
    )

    const quote = container.querySelector('blockquote.docling-quote')
    expect(quote).toBeInTheDocument()
    expect(quote?.querySelectorAll('p')).toHaveLength(2)
    expect(quote?.querySelectorAll('p')[0]).toHaveTextContent('Quoted statement.')
    expect(quote?.querySelectorAll('p')[1]).toHaveTextContent('Speaker attribution')
  })

  it('renders a labelled recommendations section with an ordered list', () => {
    render(
      <DoclingContent
        footnotes={[]}
        blocks={[
          {
            type: 'box_section',
            id: 'recommendations-1',
            title: 'Recommendations',
            variant: 'recommendations',
            blocks: [
              {
                type: 'list',
                style: 'ordered',
                start: 4,
                items: [{ text: 'Retain the semantic panel.' }],
              },
            ],
          },
        ]}
      />,
    )

    const section = screen.getByRole('region', { name: 'Recommendations' })
    expect(within(section).getByRole('heading', { name: 'Recommendations' })).toBeInTheDocument()
    expect(within(section).getByRole('list')).toHaveAttribute('start', '4')
    expect(within(section).getByText('Retain the semantic panel.')).toBeInTheDocument()
  })

  it('uses the same semantic classes and footnote structure as the HTML exporter', () => {
    const { container } = render(
      <DoclingContent
        sectionId="introduction"
        footnotes={[{ id: 'footnote-1', text: 'Supporting reference.' }]}
        blocks={[
          { type: 'paragraph', number: '1.2', text: 'Numbered paragraph.' },
          { type: 'paragraph', text: 'The disposal may occur in any manner. 1' },
          { type: 'paragraph', text: 'Published in 2016.' },
          {
            type: 'list',
            style: 'unordered',
            items: [{ text: 'List item.' }],
          },
          {
            type: 'table',
            id: 'table-1',
            caption: 'Example table',
            rows: [
              [{ text: 'Heading', rowSpan: 1, colSpan: 1, columnHeader: true, rowHeader: false, startColumn: 0 }],
              [{ text: 'Value', rowSpan: 1, colSpan: 1, columnHeader: false, rowHeader: false, startColumn: 0 }],
            ],
          },
        ]}
      />,
    )

    expect(container.querySelector('.reader-numbered-paragraph .reader-paragraph-number')).toHaveTextContent('1.2')
    expect(container.querySelector('ul.reader-source-list')).toBeInTheDocument()
    expect(container.querySelector('.docling-table-scroll table.docling-table thead th[scope="col"]')).toHaveTextContent('Heading')
    expect(container.querySelector('sup.footnote-reference a')).toHaveAttribute('href', '#footnote-1')
    expect(container.querySelector('sup.footnote-reference a')).toHaveTextContent('1')
    expect(screen.getByText('Published in 2016.').querySelector('sup')).not.toBeInTheDocument()
    expect(screen.getByText('References and footnotes (1)')).toHaveAttribute('id', 'footnotes-introduction')
    expect(screen.getByText('Supporting reference.')).toHaveAttribute('id', 'footnote-1')
    expect(container.querySelector('details.reader-footnotes[open]')).toBeInTheDocument()
  })
})
