import { Link, useLocation, useNavigate } from 'react-router-dom'
import { HeaderUtilities } from './HeaderUtilities'
import {
  converterHistoryPath,
  converterStageFromPath,
  converterStagePath,
  isAdminPath,
  isConverterStagePath,
} from '../lib/converterRoutes'
import { useKonverter } from '../state/KonverterContext'
import type { Stage } from '../types/konverter'

const stages: Array<{ stage: Stage; label: string; description: string }> = [
  { stage: 'upload', label: 'Upload', description: 'Add and process PDFs' },
  { stage: 'review', label: 'Review', description: 'Resolve flagged items' },
  { stage: 'metadata', label: 'Metadata', description: 'Confirm source details' },
  { stage: 'preview', label: 'Preview', description: 'Check and export' },
]

function brandContext(pathname: string): { eyebrow: string; description: string } {
  if (isAdminPath(pathname)) {
    return { eyebrow: 'Admin console', description: 'Manage documents and the secure audit trail' }
  }
  if (pathname === converterHistoryPath()) {
    return { eyebrow: 'Your history', description: 'Your own uploads and activity in this workspace' }
  }
  return { eyebrow: 'Reviewer console', description: 'Convert, review and export accessible reports' }
}

export function StageRail() {
  const { unlocked, doneStages } = useKonverter()
  const navigate = useNavigate()
  const location = useLocation()
  const active = converterStageFromPath(location.pathname)
  const onStagePath = isConverterStagePath(location.pathname)
  const context = brandContext(location.pathname)

  return (
    <header className="converter-header">
      <div className="converter-brand-band">
        <div className="converter-brand-inner">
          <Link className="converter-brand" to={converterStagePath('upload')} aria-label="Victorian Law Reform Commission converter home">
            <img src="/vlrc_logo.png" alt="Victorian Law Reform Commission" />
            <span className="converter-product"><strong>Konverter</strong><small>Accessible publishing workspace</small></span>
          </Link>
          <div className="converter-brand-right">
            <div className="converter-brand-context"><span>{context.eyebrow}</span><strong>{context.description}</strong></div>
            <HeaderUtilities />
          </div>
        </div>
      </div>
      {onStagePath ? (
        <nav className="rail" aria-label="Review pipeline">
          <div className="rail-inner">
            {stages.map(({ stage, label, description }, index) => (
              <button
                key={stage}
                className={`stage ${doneStages.has(stage) ? 'done' : ''}`}
                disabled={!unlocked[stage]}
                aria-current={active === stage ? 'step' : undefined}
                aria-label={`Step ${index + 1}: ${label}${doneStages.has(stage) ? ', completed' : active === stage ? ', current step' : ''}`}
                onClick={() => navigate(converterStagePath(stage))}
              >
                <span className="num"><span>{index + 1}</span></span>
                <span className="stage-copy"><span className="txt">{label}</span><span className="stage-description">{description}</span></span>
              </button>
            ))}
          </div>
        </nav>
      ) : null}
    </header>
  )
}
