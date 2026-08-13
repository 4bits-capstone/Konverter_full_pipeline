import { LogOut } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { converterStageFromPath } from '../lib/converterRoutes'
import { supabase } from '../lib/supabaseClient'
import { useKonverter } from '../state/KonverterContext'
import type { Stage } from '../types/konverter'

const stageMeta: Record<Stage, { n: number; label: string }> = {
  upload: { n: 1, label: 'Upload' },
  review: { n: 2, label: 'Review' },
  metadata: { n: 3, label: 'Metadata' },
  approval: { n: 3, label: 'Metadata' },
  preview: { n: 4, label: 'Preview' },
}

export function DocumentBar() {
  const { activeDocument, documentProcessing, reviewItems, resolvedCount } = useKonverter()
  const location = useLocation()
  const stage = converterStageFromPath(location.pathname)
  const percent = reviewItems.length ? Math.round((resolvedCount / reviewItems.length) * 100) : 0
  const circumference = 94.2
  const offset = circumference - (circumference * percent) / 100
  const processingState = activeDocument ? documentProcessing[activeDocument.id]?.state ?? 'idle' : null
  const processingLabel = processingState === 'running' ? 'Processing' : processingState === 'complete' ? 'Ready to review' : processingState === 'failed' ? 'Needs retry' : 'Queued'

  return (
    <header className="docbar">
      <div>
        <div className="docbar-title">{activeDocument?.title ?? 'No document loaded'}</div>
        <div className="docbar-meta">
          {activeDocument ? <><span className="mono">{activeDocument.fileName}</span><span>·</span><span className="mono">{activeDocument.pages ? `${activeDocument.pages} pages` : 'Page count pending'}</span><span>·</span><span>{activeDocument.publisher || processingLabel}</span></> : <span>Upload a PDF to begin</span>}
        </div>
      </div>
      {stage === 'upload' && activeDocument ? (
        <div className={`document-state-pill state-${processingState}`} aria-live="polite">
          <span className="document-state-dot" aria-hidden="true" />
          {processingLabel}
        </div>
      ) : null}
      {stage !== 'upload' && activeDocument ? (
        <div
          className="progress-pill"
          role="progressbar"
          aria-label="Review decisions completed"
          aria-valuemin={0}
          aria-valuemax={reviewItems.length}
          aria-valuenow={resolvedCount}
        >
          <svg className="progress-ring" viewBox="0 0 36 36" aria-hidden="true">
            <circle cx="18" cy="18" r="15" fill="none" stroke="var(--grey-2)" strokeWidth="4" />
            <circle cx="18" cy="18" r="15" fill="none" stroke="var(--blue)" strokeWidth="4" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset} transform="rotate(-90 18 18)" />
          </svg>
          <span><b className="mono">{resolvedCount}/{reviewItems.length}</b> decisions reviewed</span>
        </div>
      ) : null}
      <span className="stagechip">Stage {stageMeta[stage].n} · {stageMeta[stage].label}</span>
      <button
        type="button"
        className="btn btn-ghost btn-sm docbar-signout"
        onClick={() => supabase.auth.signOut()}
      >
        <LogOut />
        Sign out
      </button>
    </header>
  )
}
