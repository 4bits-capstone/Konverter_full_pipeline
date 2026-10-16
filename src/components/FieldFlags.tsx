import { Circle, Info, TriangleAlert } from 'lucide-react'
import type { MetadataFieldInfo } from '../types/konverter'

type FlagStatus = 'conflict' | 'review' | 'clear'

// Missing values and disagreeing rules are the strongest reasons to look twice.
const blockingCodes = new Set(['rule_conflict', 'missing'])

export function flagStatus(info: MetadataFieldInfo): FlagStatus {
  if (info.flags.some((flag) => flag.severity === 'review' && blockingCodes.has(flag.code))) return 'conflict'
  return info.reviewNeeded ? 'review' : 'clear'
}

const statusLabel: Record<Exclude<FlagStatus, 'clear'>, string> = { conflict: 'Rule conflict', review: 'Needs review' }
const statusClass: Record<Exclude<FlagStatus, 'clear'>, string> = { conflict: 'conf--low', review: 'conf--med' }

/** Status chip shown beside a metadata field label, only when something needs a check. Colour + icon + text (WCAG: never colour alone). */
export function FieldFlagStatus({ info, error = false }: { info: MetadataFieldInfo; error?: boolean }) {
  const status = error ? 'conflict' : flagStatus(info)
  if (status === 'clear') return null
  const label = error ? 'Value required' : statusLabel[status]
  const Icon = status === 'conflict' ? TriangleAlert : Circle
  return <span className={`conf conf--lg ${statusClass[status]}`}><Icon className="ic" aria-hidden="true" />{label}</span>
}

/** The rule notes behind the status, in plain language. Hidden when the field needs no review. */
export function FieldFlagList({ info, id }: { info: MetadataFieldInfo; id?: string }) {
  if (!info.reviewNeeded || !info.flags.length) return null
  return (
    <ul className="field-flags" id={id}>
      {info.flags.map((flag) => {
        const Icon = flag.severity === 'review' ? TriangleAlert : Info
        return (
          <li key={`${flag.code}-${flag.message}`} className={`field-flag field-flag--${flag.severity}`}>
            <Icon aria-hidden="true" />
            <span>{flag.message}</span>
          </li>
        )
      })}
    </ul>
  )
}
