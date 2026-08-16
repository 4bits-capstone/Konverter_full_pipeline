import { Files, ScrollText } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { converterAuditLogPath, converterDocumentListPath } from '../lib/converterRoutes'

export function AdminModeSwitcher({ documentCount, auditCount }: {
  documentCount: number
  auditCount: number
}) {
  return (
    <nav className="audit-mode-switcher" aria-label="Admin views">
      <NavLink
        className={({ isActive }) => `audit-mode-link${isActive ? ' is-active' : ''}`}
        to={converterDocumentListPath()}
      >
        <Files aria-hidden="true" />
        <span><strong>Doc list</strong><small>All documents</small></span>
        <b>{documentCount}</b>
      </NavLink>
      <NavLink
        className={({ isActive }) => `audit-mode-link${isActive ? ' is-active' : ''}`}
        to={converterAuditLogPath()}
      >
        <ScrollText aria-hidden="true" />
        <span><strong>Audit log</strong><small>Secure record</small></span>
        <b>{auditCount}</b>
      </NavLink>
    </nav>
  )
}
