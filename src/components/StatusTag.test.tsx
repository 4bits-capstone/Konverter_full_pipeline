import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { StatusTag } from './StatusTag'

afterEach(cleanup)

describe('StatusTag', () => {
  it('labels a pipeline-accepted footnote as system-validated, not "Accepted"', () => {
    render(<StatusTag status="accepted" reviewedBy="system" />)
    expect(screen.getByText('System-validated')).toBeInTheDocument()
    expect(screen.queryByText('Accepted')).not.toBeInTheDocument()
  })

  it('shows the ordinary "Accepted" label once a reviewer has confirmed it', () => {
    render(<StatusTag status="accepted" reviewedBy="reviewer" />)
    expect(screen.getByText('Accepted')).toBeInTheDocument()
    expect(screen.queryByText('System-validated')).not.toBeInTheDocument()
  })

  it('shows the ordinary "Accepted" label when reviewedBy is absent (legacy items)', () => {
    render(<StatusTag status="accepted" />)
    expect(screen.getByText('Accepted')).toBeInTheDocument()
  })

  it('uses a distinct CSS class for the system-validated tag so it can be styled differently', () => {
    const { container } = render(<StatusTag status="accepted" reviewedBy="system" />)
    const tag = container.querySelector('.status-tag')
    expect(tag).toHaveClass('system-validated')
    expect(tag).not.toHaveClass('accepted')
  })

  it('is unaffected by reviewedBy for non-accepted statuses', () => {
    render(<StatusTag status="pending" reviewedBy="system" />)
    expect(screen.getByText('Pending review')).toBeInTheDocument()
  })
})
