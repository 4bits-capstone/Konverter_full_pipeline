import { ArrowLeft, LockKeyhole, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { converterStagePath } from '../lib/converterRoutes'
import { AdminModeSwitcher } from './AdminModeSwitcher'

export function AdminPageLayout({ title, description, headingId, documentCount, auditCount, readOnly = false, children }: {
  title: string
  description: string
  headingId: string
  documentCount: number
  auditCount: number
  readOnly?: boolean
  children: ReactNode
}) {
  return (
    <section className="screen active audit-log-page" aria-labelledby={headingId}>
      <header className="audit-log-titlebar">
        <Link className="audit-back-link" to={converterStagePath('upload')} aria-label="Back to converter"><ArrowLeft aria-hidden="true" /></Link>
        <div><span className="eyebrow">Admin console</span><h2 id={headingId}>{title}</h2><p>{description}</p></div>
        <div className="audit-title-meta">
          <span className="audit-readonly-badge"><ShieldCheck aria-hidden="true" />Admin only</span>
          {readOnly && <span className="audit-readonly-badge"><LockKeyhole aria-hidden="true" />Read only</span>}
        </div>
      </header>
      <div className="audit-admin-layout">
        <AdminModeSwitcher documentCount={documentCount} auditCount={auditCount} />
        <div className="audit-section-content">{children}</div>
      </div>
    </section>
  )
}
