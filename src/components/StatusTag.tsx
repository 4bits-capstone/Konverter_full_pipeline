import type { ReviewStatus } from '../types/konverter'

const statusLabel: Record<ReviewStatus, string> = {
  pending: 'Pending review', accepted: 'Accepted', edited: 'Edited',
  removed: 'Removed from output',
}

export function StatusTag({ status }: { status: ReviewStatus }) {
  return <span className={`status-tag ${status}`}>{statusLabel[status]}</span>
}
