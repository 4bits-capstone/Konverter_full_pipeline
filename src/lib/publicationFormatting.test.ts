import { describe, expect, it } from 'vitest'
import { formatPublicationDate, publicationDateLine } from './publicationFormatting'

describe('publication date formatting', () => {
  it.each([
    ['2020-06-18', 'June 18, 2020'],
    ['2020-06-18T00:00:00.000Z', 'June 18, 2020'],
    ['18 June 2020', 'June 18, 2020'],
    ['18/06/2020', 'June 18, 2020'],
    ['Published on June 18th, 2020.', 'June 18, 2020'],
  ])('formats %s for the publication header', (input, expected) => {
    expect(formatPublicationDate(input)).toBe(expected)
    expect(publicationDateLine(input)).toBe(`Published on ${expected}.`)
  })

  it('preserves an unrecognised metadata date without doubling punctuation', () => {
    expect(publicationDateLine('Spring 2026.')).toBe('Published on Spring 2026.')
  })
})
