import type { Stage } from '../types/konverter'

const converterStages: Stage[] = ['upload', 'review', 'metadata', 'preview']

export function converterStagePath(stage: Stage): string {
  return `/${stage}`
}

export function converterStageFromPath(pathname: string): Stage {
  const segments = pathname.split('/').filter(Boolean)
  const candidate = segments[0] === 'converter' ? segments[1] : segments[0]
  return candidate === 'export' ? 'preview' : converterStages.includes(candidate as Stage) ? candidate as Stage : 'upload'
}

/** Whether pathname is one of the Upload/Review/Metadata/Preview workflow
 * stages (as opposed to a standalone area like /admin/* or /history) — used
 * to hide the stage rail and document bar outside the document workflow. */
export function isConverterStagePath(pathname: string): boolean {
  const segments = pathname.split('/').filter(Boolean)
  const candidate = segments[0] === 'converter' ? segments[1] : segments[0]
  return candidate === 'export' || converterStages.includes(candidate as Stage)
}

export function converterHistoryPath(): string {
  return '/history'
}

export function converterOverviewPath(): string {
  return '/admin/overview'
}

export function converterDocumentListPath(): string {
  return '/admin/documents'
}

export function converterAuditLogPath(): string {
  return '/admin/audit-log'
}

export function isAdminPath(pathname: string): boolean {
  return (
    pathname === converterOverviewPath()
    || pathname === converterDocumentListPath()
    || pathname === converterAuditLogPath()
  )
}
