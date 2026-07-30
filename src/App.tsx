import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { ApprovalPage } from './pages/ApprovalPage'
import { MetadataPage } from './pages/MetadataPage'
import { ReviewPage } from './pages/ReviewPage'
import { UploadPage } from './pages/UploadPage'
import { useKonverter } from './state/KonverterContext'
import type { Stage } from './types/konverter'

const PreviewPage = lazy(() => import('./pages/PreviewPage').then((module) => ({ default: module.PreviewPage })))

function ProtectedStage({ stage, children }: { stage: Stage; children: React.ReactNode }) {
  const { unlocked } = useKonverter()
  return unlocked[stage] ? children : <Navigate to="/upload" replace />
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/upload" replace />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="review" element={<ProtectedStage stage="review"><ReviewPage /></ProtectedStage>} />
        <Route path="metadata" element={<ProtectedStage stage="metadata"><MetadataPage /></ProtectedStage>} />
        <Route path="approval" element={<ProtectedStage stage="approval"><ApprovalPage /></ProtectedStage>} />
        <Route
          path="preview"
          element={(
            <ProtectedStage stage="preview">
              <Suspense fallback={<div className="grid min-h-[260px] place-items-center font-semibold text-muted" role="status">Loading full document preview…</div>}>
                <PreviewPage />
              </Suspense>
            </ProtectedStage>
          )}
        />
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Route>
    </Routes>
  )
}
