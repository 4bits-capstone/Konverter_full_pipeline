import { CircleHelp, History, LayoutDashboard, LogOut, Settings, UserRound } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { converterHistoryPath, converterOverviewPath, isAdminPath } from '../lib/converterRoutes'
import { supabase } from '../lib/supabaseClient'
import { useIsAdmin } from '../lib/useIsAdmin'

function ReviewGuidanceContent() {
  return (
    <div className="header-guidance-panel" role="region" aria-label="Review guidance">
      <h3>Using Konverter</h3>
      <ol>
        <li><strong>Upload</strong> — add one or more PDFs and let them process.</li>
        <li><strong>Review</strong> — resolve any items flagged with low or medium confidence.</li>
        <li><strong>Metadata</strong> — confirm the source details Docling extracted.</li>
        <li><strong>Preview</strong> — check the accessible result, then export or approve it.</li>
      </ol>
    </div>
  )
}

function AdminGuidanceContent() {
  return (
    <div className="header-guidance-panel" role="region" aria-label="Admin guidance">
      <h3>Using the admin console</h3>
      <ol>
        <li><strong>Overview</strong> — a snapshot of documents, contributors, and audit health.</li>
        <li><strong>Doc list</strong> — every document uploaded by every user, regardless of ownership.</li>
        <li><strong>Audit log</strong> — a permanent, tamper-evident record of every action taken in the workspace.</li>
      </ol>
    </div>
  )
}

function HistoryGuidanceContent() {
  return (
    <div className="header-guidance-panel" role="region" aria-label="History guidance">
      <h3>Using your history</h3>
      <ol>
        <li><strong>Documents</strong> — PDFs you've uploaded in this workspace.</li>
        <li><strong>Actions</strong> — your own activity, like edits and approvals.</li>
      </ol>
    </div>
  )
}

export function HeaderUtilities() {
  const { isAdmin, email } = useIsAdmin()
  const location = useLocation()
  const [profileOpen, setProfileOpen] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const onHistoryPage = location.pathname === converterHistoryPath()
  const onAdminPage = isAdminPath(location.pathname)
  const initials = (email ?? 'account').charAt(0).toUpperCase()
  const guidanceLabel = onAdminPage ? 'Admin guidance' : onHistoryPage ? 'History guidance' : 'Review guidance'

  const handleLogout = async () => {
    setLoggingOut(true)
    try {
      await supabase.auth.signOut()
      // AuthGate's onAuthStateChange listener resets Konverter state and
      // navigates to /upload once it sees the session go away.
    } finally {
      setLoggingOut(false)
    }
  }

  return (
    <div className="header-utilities" role="group" aria-label="Help, history and account">
      <details className="header-utility header-help">
        <summary aria-label={guidanceLabel} title={guidanceLabel}><CircleHelp aria-hidden="true" /></summary>
        {onAdminPage ? <AdminGuidanceContent /> : onHistoryPage ? <HistoryGuidanceContent /> : <ReviewGuidanceContent />}
      </details>

      <Link
        className={`header-utility-link${onHistoryPage ? ' is-active' : ''}`}
        to={converterHistoryPath()}
        aria-label="History"
        aria-current={onHistoryPage ? 'page' : undefined}
        title="History"
      >
        <History aria-hidden="true" />
      </Link>

      <details className="header-utility header-settings">
        <summary aria-label="Account settings" title="Account settings"><Settings aria-hidden="true" /></summary>
        <div className="header-settings-panel" aria-label="Account settings">
          <div className="header-account">
            <span className="header-account-avatar" aria-hidden="true">{initials}</span>
            <span>
              <strong>{email ?? 'Account'}</strong>
              {isAdmin ? <span className="header-role-badge">Admin</span> : null}
            </span>
          </div>
          <button
            className="header-profile-action"
            type="button"
            aria-expanded={profileOpen}
            aria-controls="header-profile-details"
            onClick={() => setProfileOpen((open) => !open)}
          >
            <UserRound aria-hidden="true" />
            <span>Profile</span>
          </button>
          {profileOpen ? (
            <div className="header-profile-details" id="header-profile-details">
              <span>Account role</span>
              <strong>{isAdmin ? 'Admin' : 'User'}</strong>
            </div>
          ) : null}
          <Link
            className={`header-profile-action${onHistoryPage ? ' is-active' : ''}`}
            to={converterHistoryPath()}
            aria-current={onHistoryPage ? 'page' : undefined}
            onClick={(event) => event.currentTarget.closest('details')?.removeAttribute('open')}
          >
            <History aria-hidden="true" />
            <span>History</span>
          </Link>
          {isAdmin ? (
            <Link
              className={`header-profile-action${onAdminPage ? ' is-active' : ''}`}
              to={converterOverviewPath()}
              aria-current={onAdminPage ? 'page' : undefined}
              onClick={(event) => event.currentTarget.closest('details')?.removeAttribute('open')}
            >
              <LayoutDashboard aria-hidden="true" />
              <span>Admin dashboard</span>
            </Link>
          ) : null}
          <button className="header-logout" type="button" onClick={handleLogout} disabled={loggingOut}>
            <LogOut aria-hidden="true" />
            <span>{loggingOut ? 'Signing out…' : 'Logout'}</span>
          </button>
        </div>
      </details>
    </div>
  )
}
