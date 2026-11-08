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
  // the review queue is not the same claim as a reviewer's own accept: its
  // text matched the PDF, but no one has looked at it, including the
  // italic/bold recovered from the PDF's fonts. Labelling it distinctly
  // keeps that visible.
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
