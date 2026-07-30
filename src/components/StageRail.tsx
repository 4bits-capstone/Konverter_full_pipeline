import { useLocation, useNavigate } from 'react-router-dom'
import { useKonverter } from '../state/KonverterContext'
import type { Stage } from '../types/konverter'

const stages: Array<{ stage: Stage; label: string }> = [
  { stage: 'upload', label: 'Upload' },
  { stage: 'review', label: 'Review flags' },
  { stage: 'metadata', label: 'Metadata' },
  { stage: 'approval', label: 'Approval' },
  { stage: 'preview', label: 'Preview & export' },
]

export function StageRail() {
  const { unlocked, doneStages } = useKonverter()
  const navigate = useNavigate()
  const location = useLocation()
  const active = (location.pathname.split('/')[1] || 'upload') as Stage

  return (
    <nav
      className="fixed inset-y-0 left-0 z-50 flex h-dvh w-[248px] flex-col gap-1.5 overflow-y-auto bg-brand-blue-dark px-4 py-[22px] text-[#D9E3EE] max-[820px]:static max-[820px]:h-auto max-[820px]:w-auto max-[820px]:flex-row max-[820px]:flex-wrap max-[820px]:items-center max-[820px]:gap-1 max-[820px]:overflow-visible max-[820px]:p-3"
      aria-label="Review pipeline"
    >
      <div className="mb-3.5 flex items-center gap-[11px] border-b border-white/10 px-2 pt-1 pb-5 max-[820px]:m-0 max-[820px]:border-0 max-[820px]:py-0 max-[820px]:pr-3 max-[820px]:pl-1">
        <div
          className="grid size-9 shrink-0 place-items-center rounded-lg bg-[linear-gradient(90deg,#004383_0%,#6A2F63_55%,#A93034_100%)] text-[19px] font-extrabold text-white shadow-[inset_0_0_0_1.5px_rgba(255,255,255,.25)]"
          aria-hidden="true"
        >
          K
        </div>
        <div>
          <div className="text-[19px] leading-none font-extrabold tracking-[-.01em] text-white">Konverter</div>
          <div className="mt-[3px] text-[11px] font-semibold tracking-[.14em] text-[#93AFC9] uppercase max-[820px]:hidden">Reviewer Console</div>
        </div>
      </div>
      <div className="mt-1.5 px-2.5 pt-1.5 pb-1 text-[10.5px] font-extrabold tracking-[.16em] text-[#8AA6C1] uppercase max-[820px]:hidden">Pipeline</div>
      {stages.map(({ stage, label }, index) => (
        <button
          key={stage}
          className="group flex w-full items-center gap-3 rounded-lg border-0 bg-transparent px-2.5 py-[11px] text-left text-sm font-medium text-[#C3D5E6] transition-colors hover:not-disabled:bg-white/[.06] hover:not-disabled:text-[#EDF3F9] aria-[current=true]:bg-white/[.11] aria-[current=true]:text-white disabled:cursor-not-allowed disabled:opacity-40 max-[820px]:w-auto"
          disabled={!unlocked[stage]}
          aria-current={active === stage ? 'true' : undefined}
          onClick={() => navigate(`/${stage}`)}
        >
          <span
            className={`grid size-6 shrink-0 place-items-center rounded-full border-[1.5px] font-mono text-xs font-medium tabular-nums ${
              doneStages.has(stage)
                ? "border-status-high bg-status-high text-white after:font-sans after:text-xs after:font-bold after:content-['✓'] [&>span]:hidden"
                : 'border-white/30 text-inherit group-aria-[current=true]:border-white group-aria-[current=true]:bg-white group-aria-[current=true]:text-ink'
            }`}
          >
            <span>{index + 1}</span>
          </span>
          <span className="max-[820px]:hidden">{label}</span>
        </button>
      ))}
      <div className="mt-auto border-t border-white/10 px-2.5 pt-3.5 pb-0.5 text-xs leading-[1.45] text-[#93AFC9] max-[820px]:hidden">
        Human-in-the-loop review.<br />Every AI decision and edit is <b className="font-semibold text-[#D6E4F0]">logged for audit</b>.
      </div>
    </nav>
  )
}
