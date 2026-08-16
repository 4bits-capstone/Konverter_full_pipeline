import { Navigate, Outlet } from 'react-router-dom'
import { useIsAdmin } from '../lib/useIsAdmin'

export function RequireAdmin() {
  const { isAdmin, loading } = useIsAdmin()

  if (loading) {
    return <div className="page-loading" role="status">Checking access…</div>
  }

  if (!isAdmin) {
    return <Navigate to="/upload" replace />
  }

  return <Outlet />
}
