import type { Stage } from '../types/konverter'

const converterStages: Stage[] = ['upload', 'review', 'metadata', 'preview']

export function converterStagePath(stage: Stage): string {
  return `/${stage}`
}

export function converterStageFromPath(pathname: string): Stage {
  const segments = pathname.split('/').filter(Boolean)
  const candidate = segments[0] === 'converter' ? segments[1] : segments[0]
  return converterStages.includes(candidate as Stage) ? candidate as Stage : 'upload'
}
