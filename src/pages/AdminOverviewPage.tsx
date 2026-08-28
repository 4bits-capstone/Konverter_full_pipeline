import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Clock,
  Files,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  UserRound,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { AdminModeSwitcher } from '../components/AdminModeSwitcher'
import { ActionBadge, ActorChip, TimeStack } from '../components/AuditActionDetail'
import { AUDIT_LOG_FETCH_LIMIT, auditChainStatus, auditEntrySummary, type AuditActionTone } from '../lib/auditFormatting'
import { converterAuditLogPath, converterStagePath } from '../lib/converterRoutes'
import { auditService, documentService } from '../services'

const RECENT_ACTIVITY_COUNT = 6

function StatTile({ icon: Icon, tone, value, label }: {
  icon: LucideIcon
  tone: AuditActionTone
  value: number
  label: string
}) {
  return (
    <div className="admin-stat-tile">
      <span className={`audit-detail-icon audit-detail-icon--${tone}`} aria-hidden="true"><Icon /></span>
      <div className="admin-stat-copy">
        <span className="admin-stat-value">{value.toLocaleString('en-AU')}</span>
        <span className="admin-stat-label">{label}</span>
      </div>
    </div>
  )
}

export function AdminOverviewPage() {
  const { data: documents = [], isLoading: documentsLoading, isError: documentsError } = useQuery({
    queryKey: ['documents', 'all'],
    queryFn: () => documentService.listAllDocuments(),
  })
  const { data: entries = [], isLoading: entriesLoading, isError: entriesError } = useQuery({
    queryKey: ['audit-log', AUDIT_LOG_FETCH_LIMIT],
    queryFn: () => auditService.list({ limit: AUDIT_LOG_FETCH_LIMIT }),
  })

  const isLoading = documentsLoading || entriesLoading
  const isError = documentsError || entriesError

  const awaitingApproval = documents.filter((document) => document.processingState === 'complete' && !document.approvedAt).length
  const processingFailures = documents.filter((document) => document.processingState === 'failed').length
  const contributors = new Set(documents.map((document) => document.uploadedByEmail).filter(Boolean)).size
  const brokenChainCount = entries.reduce(
    (count, _entry, index) => count + (auditChainStatus(entries, index) === 'broken' ? 1 : 0),
    0,
  )
  const recentEntries = entries.slice(0, RECENT_ACTIVITY_COUNT)

  return (
    <section className="screen active audit-log-page" aria-labelledby="admin-overview-heading">
      <div className="admin-page-header">
        <Link className="btn btn-ghost btn-sm" to={converterStagePath('upload')} aria-label="Back to converter">
          <ArrowLeft aria-hidden="true" />
        </Link>
        <div>
          <span className="eyebrow">Admin only</span>
          <h2 id="admin-overview-heading">Overview</h2>
          <p className="lead">A snapshot of documents, contributors, and audit health across the workspace.</p>
        </div>
      </div>

      <AdminModeSwitcher documentCount={documents.length} auditCount={entries.length} />

      {isLoading ? (
        <div className="panel panel-pad">
          <div className="page-loading" role="status">Loading overview…</div>
        </div>
      ) : isError ? (
        <div className="panel panel-pad">
          <div className="banner banner-err" role="alert">The overview could not be loaded.</div>
        </div>
      ) : (
        <>
          <div className="admin-stat-grid">
            <StatTile icon={Files} tone="info" value={documents.length} label="Total documents" />
            <StatTile
              icon={Clock}
              tone={awaitingApproval > 0 ? 'med' : 'neutral'}
              value={awaitingApproval}
              label="Awaiting approval"
            />
            <StatTile
              icon={TriangleAlert}
              tone={processingFailures > 0 ? 'low' : 'high'}
              value={processingFailures}
              label="Processing failures"
            />
            <StatTile icon={UserRound} tone="info" value={contributors} label="Contributors" />
            <StatTile icon={ScrollText} tone="neutral" value={entries.length} label="Audit events" />
            <StatTile
              icon={brokenChainCount > 0 ? ShieldAlert : ShieldCheck}
              tone={brokenChainCount > 0 ? 'low' : 'high'}
              value={brokenChainCount}
              label="Broken chain entries"
            />
          </div>

          <div className="panel panel-pad">
            <h3>Recent activity</h3>
            {recentEntries.length === 0 ? (
              <p className="hint">No audit events yet.</p>
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <caption className="sr-only">Recent audit activity</caption>
                  <thead>
                    <tr>
                      <th scope="col">Time</th>
                      <th scope="col">Actor</th>
                      <th scope="col">Action</th>
                      <th scope="col">Summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentEntries.map((entry) => (
                      <tr key={entry.id}>
                        <td><TimeStack value={entry.created_at} /></td>
                        <td><ActorChip email={entry.actor_email} /></td>
                        <td><ActionBadge action={entry.action} /></td>
                        <td className="audit-summary-cell" title={auditEntrySummary(entry)}>{auditEntrySummary(entry)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Link className="btn btn-outline btn-sm admin-recent-link" to={converterAuditLogPath()}>
              View full audit log
            </Link>
          </div>
        </>
      )}
    </section>
  )
}
