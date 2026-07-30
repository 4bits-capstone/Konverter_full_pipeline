import type { ReviewStatus } from '../types/konverter'

const statusLabel: Record<ReviewStatus, string> = {
  pending: 'Pending review',
  accepted: 'Accepted',
  edited: 'Edited',
  needs_attention: 'Needs attention',
  removed: 'Removed from output',
}

const statusClass: Record<ReviewStatus, string> = {
  pending: 'border-[#CFE0F0] bg-brand-blue-tint text-brand-blue',
  accepted: 'border-status-high-line bg-status-high-soft text-status-high',
  edited: 'border-[#CFE0F0] bg-brand-blue-soft text-brand-blue',
  needs_attention: 'border-status-low-line bg-status-low-soft text-status-low',
  removed: 'border-[#D8DCE1] bg-[#F2F4F6] text-[#596270]',
}

export function StatusTag({ status }: { status: ReviewStatus }) {
  return (
    <span className={`rounded-[5px] border px-2 py-0.5 text-[11px] font-bold tracking-[.02em] ${statusClass[status]}`}>
      {statusLabel[status]}
    </span>
  )
}
