import { useLocation } from 'react-router-dom'
import { useKonverter } from '../state/KonverterContext'
import type { Stage } from '../types/konverter'

const stageMeta: Record<Stage, { n: number; label: string }> = {
  upload: { n: 1, label: 'Upload' },
  review: { n: 2, label: 'Review' },
  metadata: { n: 3, label: 'Metadata' },
  approval: { n: 4, label: 'Approval' },
  preview: { n: 5, label: 'Preview' },
}

export function DocumentBar() {
  const { uploaded, activeDocument, reviewItems, resolvedCount, approvedAt } = useKonverter()
  const location = useLocation()
  const stage = (location.pathname.split('/')[1] || 'upload') as Stage
  const percent = reviewItems.length ? Math.round((resolvedCount / reviewItems.length) * 100) : 0
  const circumference = 94.2
  const offset = circumference - (circumference * percent) / 100

  return (
    <header className="sticky top-0 z-20 flex items-center gap-5 border-b border-line bg-white px-7 py-[13px] max-[820px]:px-4 max-[820px]:py-3">
      <div>
        <div className="text-[15px] leading-[1.3] font-semibold text-ink">{uploaded && activeDocument ? activeDocument.title : 'No document loaded'}</div>
        <div className="mt-px flex flex-wrap gap-2.5 text-xs text-muted">
          {uploaded && activeDocument ? (
            <>
              <span className="font-mono text-ink-2">{activeDocument.fileName}</span><span>·</span>
              <span className="font-mono text-ink-2">{activeDocument.pages ? `${activeDocument.pages} pages` : 'Page count pending'}</span><span>·</span>
              <span>{activeDocument.publisher}</span>
            </>
          ) : <span>Upload a legal PDF to begin</span>}
        </div>
      </div>
      {uploaded && (
        <div className="ml-auto flex items-center gap-2.5 rounded-full border border-line bg-brand-blue-tint py-1.5 pr-3.5 pl-1.5 text-[12.5px] text-ink-2 max-[820px]:hidden">
          <svg className="size-[30px] shrink-0" viewBox="0 0 36 36" aria-hidden="true">
            <circle cx="18" cy="18" r="15" fill="none" className="stroke-[#E9E9E9]" strokeWidth="4" />
            <circle cx="18" cy="18" r="15" fill="none" className="stroke-brand-blue" strokeWidth="4" strokeLinecap="round"
              strokeDasharray={circumference} strokeDashoffset={offset} transform="rotate(-90 18 18)" />
          </svg>
          <span><b className="font-mono font-semibold">{percent}%</b> reviewed</span>
        </div>
      )}
      <span className="rounded-md border border-line-strong px-[9px] py-1 text-[11px] font-semibold tracking-[.1em] text-muted uppercase">
        {approvedAt && stage === 'approval' ? 'Stage 4 · Approved' : `Stage ${stageMeta[stage].n} · ${stageMeta[stage].label}`}
      </span>
    </header>
  )
}
