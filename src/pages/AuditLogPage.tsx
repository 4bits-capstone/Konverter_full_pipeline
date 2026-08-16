import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { auditActionLabel, auditChainStatus, formatAuditDetail, formatAuditTime } from '../lib/auditFormatting'
import { converterStagePath } from '../lib/converterRoutes'
import { auditService } from '../services'

export function AuditLogPage() {
  const [search, setSearch] = useState('')
  const { data: entries = [], isLoading, isError } = useQuery({
    queryKey: ['audit-log'],
    queryFn: () => auditService.list(),
  })

  const visibleEntries = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('en-AU')
    if (!query) return entries
    return entries.filter((entry) => (
      [entry.actor_email, entry.document_id, entry.action, auditActionLabel(entry.action)]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase('en-AU')
        .includes(query)
    ))
  }, [entries, search])

  return (
    <section className="screen active" aria-labelledby="audit-log-heading">
      <div className="admin-page-header">
        <Link className="btn btn-ghost btn-sm" to={converterStagePath('upload')} aria-label="Back to converter">
          <ArrowLeft aria-hidden="true" />
        </Link>
        <div>
          <span className="eyebrow">Admin only</span>
          <h2 id="audit-log-heading">Audit log</h2>
          <p className="lead">Permanent, tamper-evident record of every action taken in the workspace.</p>
        </div>
      </div>

      <div className="panel panel-pad">
        <div className="admin-toolbar">
          <input
            className="input"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by actor, document, or action"
            aria-label="Search audit log"
          />
          <span className="admin-count">{visibleEntries.length} of {entries.length} events</span>
        </div>

        {isLoading ? (
          <div className="page-loading" role="status">Loading audit log…</div>
        ) : isError ? (
          <div className="banner banner-err" role="alert">The audit log could not be loaded.</div>
        ) : visibleEntries.length === 0 ? (
          <p className="hint">No audit events{search ? ' match this search' : ' yet'}.</p>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <caption className="sr-only">Audit log entries</caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Action</th>
                  <th scope="col">Detail</th>
                  <th scope="col">Chain</th>
                </tr>
              </thead>
              <tbody>
                {visibleEntries.map((entry) => {
                  const status = auditChainStatus(entries, entries.indexOf(entry))
                  return (
                    <tr key={entry.id}>
                      <td><time className="mono" dateTime={entry.created_at}>{formatAuditTime(entry.created_at)}</time></td>
                      <td>{entry.actor_email ?? '—'}</td>
                      <td>{auditActionLabel(entry.action)}</td>
                      <td className="admin-table-detail" title={entry.detail ? JSON.stringify(entry.detail) : undefined}>
                        {formatAuditDetail(entry.detail)}
                      </td>
                      <td>
                        {status === 'linked' ? (
                          <span className="conf conf--high" title={entry.entry_hash ?? undefined}>
                            <ShieldCheck className="ic" aria-hidden="true" />Linked
                          </span>
                        ) : status === 'broken' ? (
                          <span className="conf conf--low" title="prev_hash does not match the previous entry">
                            <ShieldAlert className="ic" aria-hidden="true" />Broken
                          </span>
                        ) : (
                          <span className="conf conf--med" title="Written before hash chaining was enabled">
                            <ShieldAlert className="ic" aria-hidden="true" />Unverifiable
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
