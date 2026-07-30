import { Check } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useKonverter } from '../state/KonverterContext'

export function Toast() {
  const { toastState } = useKonverter()
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!toastState) return
    setVisible(true)
    const timer = window.setTimeout(() => setVisible(false), 2600)
    return () => window.clearTimeout(timer)
  }, [toastState])

  return (
    <div
      className={`fixed right-6 bottom-6 z-[300] flex min-w-[220px] items-center gap-2.5 rounded-lg bg-brand-blue-dark px-[18px] py-3.5 text-sm font-semibold text-white shadow-overlay transition-all duration-200 ${
        visible ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-3 opacity-0'
      }`}
      role="status"
      aria-live="polite"
    >
      <Check className="size-[18px] text-status-high-line" aria-hidden="true" />
      <span>{toastState?.message ?? 'Saved'}</span>
    </div>
  )
}
