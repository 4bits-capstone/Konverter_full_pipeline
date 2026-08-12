import { Check, Circle, TriangleAlert } from 'lucide-react'
import type { ConfidenceBand } from '../types/konverter'

interface Props { band: ConfidenceBand; score: number; compact?: boolean; size?: 'md' | 'lg' }
const label: Record<ConfidenceBand, string> = { high: 'High', med: 'Medium', low: 'Low' }
const cls: Record<ConfidenceBand, string> = { high: 'conf--high', med: 'conf--med', low: 'conf--low' }

export function ConfidenceBadge({ band, score, compact = false, size = 'md' }: Props) {
  const Icon = band === 'high' ? Check : band === 'low' ? TriangleAlert : Circle
  const percentage = `${Math.round(score * 100)}%`
  return <span className={`conf ${cls[band]} ${size === 'lg' ? 'conf--lg' : ''}`} style={compact ? { fontSize: 12, padding: '5px 10px' } : undefined} aria-label={`${label[band]} confidence, ${percentage}`}><Icon className="ic" aria-hidden="true" />{label[band]} <span className="score">{percentage}</span></span>
}
