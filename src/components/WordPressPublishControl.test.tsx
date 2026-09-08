import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { publicationService, resetTestServices } from '../test/serviceMocks'
import type { WordPressPublication } from '../types/konverter'
import { WordPressPublishControl } from './WordPressPublishControl'

vi.mock('../services', () => import('../test/serviceMocks'))
beforeEach(() => {
  resetTestServices()
  // JSDOM does not implement the native dialog top layer.
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })
function renderControl() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <WordPressPublishControl documentId="test-document" onPublished={vi.fn()} />
  </QueryClientProvider>)
}
async function openChoices(name = 'Publish to WordPress') {
  const button = await screen.findByRole('button', { name })
  await waitFor(() => expect(button).toBeEnabled())
  button.focus()
  fireEvent.click(button)
  return screen.getByRole('dialog')
}

describe('WordPress publishing choices', () => {
  it('defaults to draft and cancels without publishing, restoring focus', async () => {
    const publish = vi.spyOn(publicationService, 'publishToWordPress')
    renderControl()
    const dialog = await openChoices()
    expect(within(dialog).getByRole('radio', { name: /Save draft/ })).toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish to WordPress' })).toHaveFocus()
    expect(publish).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Publish to WordPress' }))
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(publish).not.toHaveBeenCalled()
  })

  it('saves a draft, then explicitly publishes one live page and removes publishing choices', async () => {
    const publish = vi.spyOn(publicationService, 'publishToWordPress')
    renderControl()
    fireEvent.click(within(await openChoices()).getByRole('button', { name: 'Save draft' }))
    const view = await screen.findByRole('link', { name: 'View draft' })
    expect(view).toHaveAttribute('href', 'https://vlrc.komosion.com/?page_id=26036&preview=true')
    expect(view).toHaveAttribute('rel', 'noopener noreferrer')
    expect(publish).toHaveBeenCalledExactlyOnceWith('test-document', 'draft')
    expect(document.querySelector('a[href*="wp-admin"]')).toBeNull()
    const dialog = await openChoices('Publish live')
    expect(dialog).toHaveTextContent('one separate live page')
    expect(within(dialog).queryByRole('radio', { name: /Save draft/ })).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Publish live' }))
    expect(await screen.findByRole('link', { name: 'View live page' })).toHaveAttribute('href', 'https://vlrc.komosion.com/?page_id=26036')
    expect(publish).toHaveBeenNthCalledWith(2, 'test-document', 'publish')
    expect(screen.queryByRole('button', { name: 'Publish live' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Publish to WordPress' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View draft' })).not.toBeInTheDocument()
  })

  it('supports publishing directly live without first creating a draft', async () => {
    const publish = vi.spyOn(publicationService, 'publishToWordPress')
    renderControl()
    const dialog = await openChoices()
    fireEvent.click(within(dialog).getByRole('radio', { name: /Publish live/ }))
    expect(dialog).toHaveTextContent('available to visitors immediately')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Publish live' }))
    expect(await screen.findByRole('link', { name: 'View live page' })).toBeInTheDocument()
    expect(publish).toHaveBeenCalledExactlyOnceWith('test-document', 'publish')
  })

  it('restores an existing live page without offering any publish or draft action', async () => {
    await publicationService.publishToWordPress('test-document', 'publish')
    const publish = vi.spyOn(publicationService, 'publishToWordPress')
    renderControl()
    expect(await screen.findByRole('link', { name: 'View live page' })).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(publish).not.toHaveBeenCalled()
  })

  it('waits for the saved status and disables duplicate clicks while publishing', async () => {
    let finish!: (state: WordPressPublication | null) => void
    vi.spyOn(publicationService, 'getWordPressPublication').mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const publish = vi.spyOn(publicationService, 'publishToWordPress').mockImplementation(() => new Promise(() => {}))
    renderControl()
    expect(screen.getByRole('button', { name: 'Publish to WordPress' })).toBeDisabled()
    finish(null)
    const dialog = await openChoices()
    const save = within(dialog).getByRole('button', { name: 'Save draft' })
    fireEvent.click(save)
    fireEvent.click(save)
    expect(await screen.findByRole('button', { name: 'Publishing…' })).toBeDisabled()
    expect(publish).toHaveBeenCalledTimes(1)
  })

  it('recovers a lost publishing response by reading the saved result, without retrying the write', async () => {
    const original = publicationService.publishToWordPress
    const publish = vi.spyOn(publicationService, 'publishToWordPress').mockImplementation(async (...args) => {
      await original(...args)
      throw new Error('Connection interrupted')
    })
    renderControl()
    fireEvent.click(within(await openChoices()).getByRole('button', { name: 'Save draft' }))
    expect(await screen.findByRole('link', { name: 'View draft' })).toBeInTheDocument()
    expect(publish).toHaveBeenCalledTimes(1)
  })

  it('keeps publishing disabled when status cannot be read', async () => {
    vi.spyOn(publicationService, 'getWordPressPublication').mockRejectedValueOnce(new Error('Unavailable'))
    const publish = vi.spyOn(publicationService, 'publishToWordPress')
    renderControl()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load WordPress publishing status')
    expect(screen.getByRole('button', { name: 'Publish to WordPress' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Check status again' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Publish to WordPress' })).toBeEnabled())
    expect(publish).not.toHaveBeenCalled()
  })
})
