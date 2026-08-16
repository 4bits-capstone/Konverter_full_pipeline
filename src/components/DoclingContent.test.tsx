import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DoclingContent } from './DoclingContent'

describe('DoclingContent Box Sections', () => {
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
        footnotes={[{ id: 'note-1', text: 'Supporting reference.' }]}
        blocks={[
          { type: 'paragraph', number: '1.2', text: 'Numbered paragraph.' },
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

    expect(container.querySelector('.numbered-paragraph')).toBeInTheDocument()
    expect(container.querySelector('ul.source-list')).toBeInTheDocument()
    expect(container.querySelector('.table-scroll thead th[scope="col"]')).toHaveTextContent('Heading')
    expect(screen.getByRole('heading', { name: 'References and footnotes' })).toHaveAttribute('id', 'footnotes-introduction')
    expect(screen.getByText('Supporting reference.')).toHaveAttribute('id', 'note-1')
    expect(container.querySelector('details.reader-footnotes')).not.toBeInTheDocument()
  })
})
