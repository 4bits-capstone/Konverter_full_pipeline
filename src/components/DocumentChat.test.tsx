import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DocumentChat, parseChatBlocks } from './DocumentChat'

vi.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: 'test-token' } } }),
    },
  },
}))

describe('parseChatBlocks', () => {
  it('splits bold-prefixed prose, a bullet list, and a numbered list into blocks', () => {
    const blocks = parseChatBlocks(
      '**Summary**\n\n- First point\n- Second point\n\n1. Step one\n2. Step two',
    )
    expect(blocks).toEqual([
      { kind: 'paragraph', text: '**Summary**' },
      { kind: 'bullet-list', items: ['First point', 'Second point'] },
      { kind: 'numbered-list', items: ['Step one', 'Step two'] },
    ])
  })

  it('joins consecutive non-list lines into a single paragraph', () => {
    const blocks = parseChatBlocks('Line one\nLine two')
    expect(blocks).toEqual([{ kind: 'paragraph', text: 'Line one Line two' }])
  })

  it('stops a paragraph as soon as a list line starts', () => {
    const blocks = parseChatBlocks('Intro line\n- item one')
    expect(blocks).toEqual([
      { kind: 'paragraph', text: 'Intro line' },
      { kind: 'bullet-list', items: ['item one'] },
    ])
  })
})

describe('DocumentChat', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: null,
        text: async () => 'The **key point** is:\n- one\n- two',
      }),
    )
  })

  afterEach(() => {
    cleanup()
  })

  it('starts collapsed as a floating button and opens into the chat panel', () => {
    render(<DocumentChat documentId="doc-1" />)

    const fab = screen.getByRole('button', { name: 'Ask about this document' })
    expect(screen.queryByRole('log')).not.toBeInTheDocument()

    fireEvent.click(fab)
    expect(screen.getByRole('log')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ask about this document' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Close chat' }))
    const closingPanel = screen.getByRole('log').closest('.chat-widget-panel')
    expect(closingPanel).toHaveClass('is-closing')
    fireEvent.animationEnd(closingPanel!)
    expect(screen.queryByRole('log')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ask about this document' })).toBeInTheDocument()
  })

  it('sends a starter prompt immediately when clicked', async () => {
    render(<DocumentChat documentId="doc-1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Ask about this document' }))

    fireEvent.click(screen.getByRole('button', { name: 'Summarize this document' }))

    expect(screen.getByText('Summarize this document', { selector: 'p' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('key point')).toBeInTheDocument())
  })

  it('renders markdown-lite formatting from the reply and keeps the visible log silent for screen readers', async () => {
    render(<DocumentChat documentId="doc-1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Ask about this document' }))

    fireEvent.change(screen.getByLabelText('Ask a question about this document'), {
      target: { value: 'What is the key point?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(screen.getByRole('log')).toHaveAttribute('aria-live', 'off')

    await waitFor(() => expect(screen.getByText('key point')).toBeInTheDocument())
    expect(screen.getByText('key point').tagName).toBe('STRONG')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('announces the completed reply once through a hidden live region', async () => {
    render(<DocumentChat documentId="doc-1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Ask about this document' }))

    fireEvent.change(screen.getByLabelText('Ask a question about this document'), {
      target: { value: 'What is the key point?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByText(/Assistant replied/)).toBeInTheDocument())
    expect(screen.getByText(/Assistant replied/)).toHaveTextContent(
      'Assistant replied: The key point is: one two',
    )
  })
})
