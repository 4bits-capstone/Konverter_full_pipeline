import { Files, LayoutDashboard, ScrollText } from 'lucide-react'
import type { CSSProperties } from 'react'
import { NavLink } from 'react-router-dom'
import { converterAuditLogPath, converterDocumentListPath, converterOverviewPath } from '../lib/converterRoutes'

export function AdminModeSwitcher({ documentCount, auditCount }: {
  documentCount: number
  auditCount: number
}) {
  const style = { '--switcher-tabs': 3 } as CSSProperties

  return (
    <nav className="audit-mode-switcher" aria-label="Admin views" style={style}>
      <NavLink
        className={({ isActive }) => `audit-mode-link${isActive ? ' is-active' : ''}`}
        to={converterOverviewPath()}
      >
        <LayoutDashboard aria-hidden="true" />
        <span><strong>Overview</strong><small>At a glance</small></span>
      </NavLink>
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
