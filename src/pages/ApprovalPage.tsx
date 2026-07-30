import { Check, CircleCheck, RefreshCcw, TriangleAlert } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { approvalService } from '../services'
import { useKonverter } from '../state/KonverterContext'

export function ApprovalPage() {
  const navigate = useNavigate()
  const {
    activeDocument,
    activeDocumentId,
    pendingCount,
    reviewItems,
    metadata,
    metadataResolved,
    setMetadataResolved,
    manualChecks,
    toggleManualCheck,
    setAllManualChecks,
    resolveAllReviews,
    approvalReady,
    approvedAt,
    setApprovedAt,
    unlock,
    markDone,
    showToast,
    resetWorkflow,
  } = useKonverter()
  const [modalOpen, setModalOpen] = useState(false)
  const confirmRef = useRef<HTMLButtonElement | null>(null)
  const tableFlags = reviewItems.filter((item) => item.type === 'table' || item.type === 'document_index').length
  const pictureFlags = reviewItems.filter((item) => item.type === 'picture').length
  const manualChecklist = [
    { key: 'headings' as const, title: 'Heading structure checked', sub: 'Confirm chapter hierarchy is correct' },
    { key: 'tables' as const, title: 'Tables & figures checked', sub: `${tableFlags} table flag${tableFlags === 1 ? '' : 's'}, ${pictureFlags} picture flag${pictureFlags === 1 ? '' : 's'}` },
    { key: 'citations' as const, title: 'Citations checked', sub: 'Verify the required citation house style' },
    { key: 'a11y' as const, title: 'Accessibility output ready', sub: 'Semantic output checks pass' },
  ]

  const reasons = useMemo(() => {
    const list: string[] = []
    if (pendingCount) list.push(`${pendingCount} flagged item${pendingCount !== 1 ? 's' : ''} still pending`)
    if (!metadataResolved) list.push('the document metadata has not been confirmed')
    const manual = Object.values(manualChecks).filter((value) => !value).length
    if (manual) list.push(`${manual} checklist confirmation${manual !== 1 ? 's' : ''} outstanding`)
    return list
  }, [manualChecks, metadataResolved, pendingCount])

  const autoResolve = async () => {
    await resolveAllReviews()
    setAllManualChecks(true)
    const metadataComplete = Boolean(
      metadata.title.trim()
      && metadata.publisher.trim()
      && metadata.publishedDate.trim(),
    )
    if (!metadataResolved && metadataComplete) {
      setMetadataResolved(true)
    }
    showToast(
      metadataComplete
        ? 'All remaining checks resolved'
        : 'Review flags and checklist resolved; metadata still needs confirmation',
    )
  }

  const approve = async () => {
    const result = await approvalService.approve(activeDocumentId ?? undefined)
    setApprovedAt(result.approvedAt)
    unlock('preview')
    markDone('approval')
    setModalOpen(false)
    showToast('Document approved · output ready to generate')
  }

  const openModal = () => {
    setModalOpen(true)
    window.setTimeout(() => confirmRef.current?.focus(), 0)
  }

  const revoke = async () => {
    if (activeDocumentId) await approvalService.revoke(activeDocumentId)
    setApprovedAt(null)
    showToast('Approval revoked')
  }

  const rejectAndReupload = () => {
    resetWorkflow()
    navigate('/upload')
    showToast('Document removed from review. Add the corrected file to start again.')
  }

  return (
    <section className="screen active" aria-labelledby="approval-heading">
      <div className="section-title">
        <span className="eyebrow">Stage 4 of 5</span>
        <h2 id="approval-heading" style={{ marginTop: 8 }}>Approve document</h2>
        <p className="lead">Final human sign-off. The document cannot generate published output until every required task is complete.</p>
      </div>

      {!approvedAt ? (
        <>
          {!approvalReady && (
            <div className="banner banner-warn" style={{ marginBottom: 20 }}>
              <TriangleAlert />
              <div><b>Approval is blocked.</b> You still need to resolve: {reasons.join(', ')}.</div>
            </div>
          )}

          <div className="approve-grid">
            <div className="panel">
              <div className="panel-head"><h3>Approval checks</h3></div>
              <div className="approval-check-sections">
                <section aria-labelledby="system-checks-heading">
                  <div className="approval-check-heading">
                    <div><span className="eyebrow">System checks</span><h4 id="system-checks-heading">Automated readiness</h4></div>
                    <span>Updated from review and metadata</span>
                  </div>
                <ul className="checklist">
                  <li className={`check ${pendingCount === 0 ? 'ok' : 'blocked'}`}>
                    <div className="checkbox" role="checkbox" aria-checked={pendingCount === 0} aria-readonly="true"><Check /></div>
                    <div><div className="check-txt">All flagged items reviewed</div><div className="check-sub">{pendingCount ? `${pendingCount} of ${reviewItems.length} items still pending` : `All ${reviewItems.length} items reviewed`}</div></div>
                  </li>
                  <li className={`check ${metadataResolved ? 'ok' : 'blocked'}`}>
                    <div className="checkbox" role="checkbox" aria-checked={metadataResolved} aria-readonly="true"><Check /></div>
                    <div><div className="check-txt">Metadata checked</div><div className="check-sub">{metadataResolved ? 'Document metadata confirmed' : 'Metadata confirmation required'}</div></div>
                  </li>
                </ul>
                </section>
                <section aria-labelledby="reviewer-checks-heading">
                  <div className="approval-check-heading">
                    <div><span className="eyebrow">Reviewer checks</span><h4 id="reviewer-checks-heading">Human confirmation</h4></div>
                    <span>Complete each check before approval</span>
                  </div>
                  <ul className="checklist">
                  {manualChecklist.map((item) => (
                    <li key={item.key} className={`check ${manualChecks[item.key] ? 'ok' : ''}`}>
                      <button
                        type="button"
                        className="checkbox"
                        role="checkbox"
                        aria-checked={manualChecks[item.key]}
                        aria-label={item.title}
                        onClick={() => toggleManualCheck(item.key)}
                      ><Check /></button>
                      <div><div className="check-txt">{item.title}</div><div className="check-sub">{item.sub}</div></div>
                    </li>
                  ))}
                </ul>
                </section>
              </div>
              <div className="actionbar">
                <button className="btn btn-seal" disabled={!approvalReady} onClick={openModal}><CircleCheck />Approve document</button>
                <button className="btn btn-outline" onClick={() => navigate('/review')}>Return to review</button>
                <div className="spacer" />
                <button className="btn btn-ghost btn-sm" style={{ color: 'var(--muted)' }} onClick={autoResolve}>Resolve all</button>
              </div>
            </div>

            <div className="panel panel-pad document-summary-card">
              <div className="field-label">Document summary</div>
              <ul className="summary-list">
                <li><span className="k">Document title</span><span className="v">{activeDocument?.title ?? 'No document selected'}</span></li>
                <li><span className="k">File name</span><span className="v mono full-file-name">{activeDocument?.fileName ?? 'Unavailable'}</span></li>
                <li><span className="k">Pages</span><span className="v mono">{activeDocument?.pages || 'Unavailable'}</span></li>
                <li><span className="k">Review status</span><span className="v"><span className={`status-tag ${pendingCount ? 'pending' : 'accepted'}`}>{pendingCount ? 'In progress' : 'Reviewed'}</span></span></li>
                <li><span className="k">Metadata status</span><span className="v"><span className={`status-tag ${metadataResolved ? 'accepted' : 'needs_attention'}`}>{metadataResolved ? 'Complete' : '1 unresolved'}</span></span></li>
                <li><span className="k">Unresolved flags</span><span className="v mono">{pendingCount}</span></li>
              </ul>
              <div className="reupload-action">
                <strong>Need to replace the whole document?</strong>
                <p>This clears the current review and returns you to upload.</p>
                <button className="btn btn-danger" type="button" onClick={rejectAndReupload}><RefreshCcw />Reject &amp; re-upload</button>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="panel approved-seal">
          <div className="seal-badge" aria-hidden="true"><CircleCheck /></div>
          <h2 style={{ fontSize: 24 }}>Document approved</h2>
          <p className="lead" style={{ margin: '8px auto 0' }}>Approved by <b>you</b> on <span className="mono">{new Date(approvedAt).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })} {new Date(approvedAt).toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' })}</span>. The accessible output can now be generated and exported.</p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', marginTop: 22 }}>
            <button className="btn btn-primary" onClick={() => navigate('/preview')}>View landing page preview →</button>
            <button className="btn btn-outline" onClick={revoke}>Revoke approval</button>
          </div>
        </div>
      )}

      {modalOpen && (
        <div className="overlay show" onMouseDown={(event) => event.target === event.currentTarget && setModalOpen(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="approve-modal-title" onKeyDown={(event) => event.key === 'Escape' && setModalOpen(false)}>
            <div className="modal-ic"><CircleCheck /></div>
            <h3 id="approve-modal-title">Approve this document?</h3>
            <p>Once approved, Konverter will generate the accessible HTML and JSON-LD output. This action is recorded in the audit trail against your account. You can revoke approval before export.</p>
            <div className="modal-actions">
              <button className="btn btn-outline" onClick={() => setModalOpen(false)}>Cancel</button>
              <button ref={confirmRef} className="btn btn-seal" onClick={approve}>Yes, approve</button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
