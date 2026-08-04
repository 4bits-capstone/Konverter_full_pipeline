import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DoclingContent } from './DoclingContent'

describe('DoclingContent callouts', () => {
  it('renders a labelled recommendations aside with an ordered list', () => {
    render(
      <DoclingContent
        footnotes={[]}
        blocks={[
          {
            type: 'callout',
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

    const aside = screen.getByRole('complementary', { name: 'Recommendations' })
    expect(within(aside).getByRole('heading', { name: 'Recommendations' })).toBeInTheDocument()
    expect(within(aside).getByRole('list')).toHaveAttribute('start', '4')
    expect(within(aside).getByText('Retain the semantic panel.')).toBeInTheDocument()
  })
})
