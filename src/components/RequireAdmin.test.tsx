import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RequireAdmin } from './RequireAdmin'

const getSession = vi.fn()

vi.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: () => getSession(),
      onAuthStateChange: vi.fn().mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } }),
    },
  },
}))

function renderGuarded(initialPath = '/admin/audit-log') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/upload" element={<div>Upload page</div>} />
        <Route element={<RequireAdmin />}>
          <Route path="/admin/audit-log" element={<div>Secret audit content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('RequireAdmin', () => {
  it('redirects a regular user to /upload without rendering the protected route', async () => {
    getSession.mockResolvedValue({ data: { session: { user: { app_metadata: {} } } } })
    renderGuarded()
    expect(await screen.findByText('Upload page')).toBeInTheDocument()
    expect(screen.queryByText('Secret audit content')).not.toBeInTheDocument()
  })

  it('renders the protected route for an admin user', async () => {
    getSession.mockResolvedValue({ data: { session: { user: { app_metadata: { role: 'admin' } } } } })
    renderGuarded()
    expect(await screen.findByText('Secret audit content')).toBeInTheDocument()
  })

  it('redirects when there is no session at all', async () => {
    getSession.mockResolvedValue({ data: { session: null } })
    renderGuarded()
    expect(await screen.findByText('Upload page')).toBeInTheDocument()
  })
})
