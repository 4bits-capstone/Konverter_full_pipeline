import type { ReviewItem, ReviewStatus } from '../types/konverter'

const statusLabel: Record<ReviewStatus, string> = {
  pending: 'Pending review', accepted: 'Accepted', edited: 'Edited',
  removed: 'Removed from output',
}

export function StatusTag({
  status,
  reviewedBy,
}: {
  status: ReviewStatus
  reviewedBy?: ReviewItem['reviewedBy']
}) {
  // An "accepted" footnote the pipeline pre-accepted before anyone opened
  // the review queue is not the same claim as a reviewer's own accept —
  // Docling cannot preserve italics on PDF text (verified directly against
  // this project's own Docling install; see BACKEND_AUDIT.md), so an
  // auto-accepted legal citation may already have silently lost styling no
  // one has checked for. Labelling it distinctly keeps that gap visible.
  if (status === 'accepted' && reviewedBy === 'system') {
    return (
      <span
        className="status-tag system-validated"
        title="Accepted automatically by the pipeline — no reviewer has looked at this item yet"
      >
        System-validated
      </span>
    )
  }
  return <span className={`status-tag ${status}`}>{statusLabel[status]}</span>
}
