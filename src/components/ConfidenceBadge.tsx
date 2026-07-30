import { Check, Circle, TriangleAlert } from 'lucide-react'
import type { ConfidenceBand } from '../types/konverter'

interface Props {
  band: ConfidenceBand
  score: number
  compact?: boolean
  size?: 'md' | 'lg'
}

const label: Record<ConfidenceBand, string> = { high: 'High', med: 'Medium', low: 'Low' }
const cls: Record<ConfidenceBand, string> = {
  high: 'border-status-high-line bg-status-high-soft text-status-high',
  med: 'border-status-medium-line bg-status-medium-soft text-status-medium',
  low: 'border-status-low-line bg-status-low-soft text-status-low',
}

export function ConfidenceBadge({ band, score, compact = false, size = 'md' }: Props) {
  const Icon = band === 'high' ? Check : band === 'low' ? TriangleAlert : Circle
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-md border font-sans text-[11.5px] font-bold tracking-[.01em] ${cls[band]} ${
        size === 'lg' ? 'gap-[7px] rounded-lg px-[11px] py-[5px] text-[13px] [&>svg]:size-[15px]' : 'gap-1.5 py-[3px] pr-2 pl-1.5 [&>svg]:size-[13px]'
      }`}
      style={compact ? { fontSize: 12, padding: '5px 10px' } : undefined}
    >
      <Icon className="shrink-0" aria-hidden="true" />
      {label[band]} <span className="font-mono font-medium opacity-85">{score.toFixed(2)}</span>
    </span>
  )
}
