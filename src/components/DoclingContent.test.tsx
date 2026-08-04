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
})
