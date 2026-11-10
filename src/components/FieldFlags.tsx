import { Circle, Info, SearchX, TriangleAlert } from 'lucide-react'
import type { MetadataFieldInfo } from '../types/konverter'

type FlagStatus = 'missing' | 'conflict' | 'review' | 'clear'

const hasReviewFlag = (info: MetadataFieldInfo, code: string) =>
  info.flags.some((flag) => flag.severity === 'review' && flag.code === code)

export function flagStatus(info: MetadataFieldInfo): FlagStatus {
  // A field with no value has nothing to conflict with, so it gets its own
  // status rather than borrowing "Rule conflict".
  if (hasReviewFlag(info, 'missing')) return 'missing'
  if (hasReviewFlag(info, 'rule_conflict')) return 'conflict'
  return info.reviewNeeded ? 'review' : 'clear'
}

type ChipStatus = Exclude<FlagStatus, 'clear'> | 'required'

const statusLabel: Record<ChipStatus, string> = {
  missing: 'Not found',
  conflict: 'Rule conflict',
  review: 'Needs review',
  required: 'Value required',
}
const statusClass: Record<ChipStatus, string> = {
  missing: 'conf--low',
  conflict: 'conf--low',
  review: 'conf--med',
  required: 'conf--low',
}
const statusIcon: Record<ChipStatus, typeof Circle> = {
  missing: SearchX,
  conflict: TriangleAlert,
  review: Circle,
  required: TriangleAlert,
}

/** Status chip shown beside a metadata field label, only when something needs a check. Colour + icon + text (WCAG: never colour alone). */
export function FieldFlagStatus({ info, error = false }: { info: MetadataFieldInfo; error?: boolean }) {
  const flag = flagStatus(info)
  if (!error && flag === 'clear') return null
  const status: ChipStatus = error ? 'required' : (flag as ChipStatus)
  const Icon = statusIcon[status]
  return <span className={`conf conf--lg ${statusClass[status]}`}><Icon className="ic" aria-hidden="true" />{statusLabel[status]}</span>
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
