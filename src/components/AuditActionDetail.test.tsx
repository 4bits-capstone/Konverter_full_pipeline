import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AuditChangePreview, changeFieldLabel } from './AuditActionDetail'

afterEach(cleanup)

describe('AuditChangePreview', () => {
  it('shows a bold/italic edit with a plain field name and readable values', () => {
    render(
      <AuditChangePreview
        before={{ corrected_styles: 'italic: "Smith v Jones"' }}
        after={{ corrected_styles: 'bold + italic: "Smith v Jones"' }}
      />,
    )

    expect(screen.getByText('Bold / italic')).toBeInTheDocument()
    expect(screen.queryByText('corrected_styles')).not.toBeInTheDocument()
    expect(screen.getByText('italic: "Smith v Jones"')).toBeInTheDocument()
    expect(screen.getByText('bold + italic: "Smith v Jones"')).toBeInTheDocument()
  })

  it('shows removed styling as empty', () => {
    render(<AuditChangePreview before={{ corrected_styles: 'bold: "12 CLR"' }} after={{ corrected_styles: null }} />)
    expect(screen.getByText('Empty')).toBeInTheDocument()
  })

  it('falls back to a readable name for unknown fields', () => {
    expect(changeFieldLabel('corrected_text')).toBe('Text')
    expect(changeFieldLabel('some_new_field')).toBe('some new field')
  })
})
