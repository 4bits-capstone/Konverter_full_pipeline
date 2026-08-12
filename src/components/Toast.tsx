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
  return <div className={`toast ${visible ? 'show' : ''}`} role="status" aria-live="polite"><Check aria-hidden="true" /><span>{toastState?.message ?? 'Saved'}</span></div>
}
