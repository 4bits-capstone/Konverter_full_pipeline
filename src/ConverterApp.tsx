import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { RequireAdmin } from './components/RequireAdmin'
import { AdminOverviewPage } from './pages/AdminOverviewPage'
import { AuditLogPage } from './pages/AuditLogPage'
import { DocumentListPage } from './pages/DocumentListPage'
import { HistoryPage } from './pages/HistoryPage'
import { MetadataPage } from './pages/MetadataPage'
import { ReviewPage } from './pages/ReviewPage'
import { UploadPage } from './pages/UploadPage'
import { useKonverter } from './state/KonverterContext'
import type { Stage } from './types/konverter'
import './styles/converter.css'
import './styles/converter-library-theme.css'
import './styles/preview.css'

const PreviewPage = lazy(() => import('./pages/PreviewPage').then((module) => ({ default: module.PreviewPage })))

function ProtectedStage({ stage, children }: { stage: Stage; children: React.ReactNode }) {
  const { unlocked } = useKonverter()
  return unlocked[stage] ? children : <Navigate to="/upload" replace />
}

export default function ConverterApp() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/upload" replace />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="review" element={<ProtectedStage stage="review"><ReviewPage /></ProtectedStage>} />
        <Route path="metadata" element={<ProtectedStage stage="metadata"><MetadataPage /></ProtectedStage>} />
        <Route path="approval" element={<Navigate to="/metadata" replace />} />
        <Route
          path="preview"
          element={(
            <ProtectedStage stage="preview">
              <Suspense fallback={<div className="page-loading" role="status">Loading full document preview…</div>}>
                <PreviewPage />
              </Suspense>
            </ProtectedStage>
          )}
        />
        <Route path="history" element={<HistoryPage />} />
        <Route element={<RequireAdmin />}>
          <Route path="admin/overview" element={<AdminOverviewPage />} />
          <Route path="admin/documents" element={<DocumentListPage />} />
          <Route path="admin/audit-log" element={<AuditLogPage />} />
        </Route>
        <Route path="converter/upload" element={<Navigate to="/upload" replace />} />
        <Route path="converter/review" element={<Navigate to="/review" replace />} />
        <Route path="converter/metadata" element={<Navigate to="/metadata" replace />} />
        <Route path="converter/approval" element={<Navigate to="/metadata" replace />} />
        <Route path="converter/preview" element={<Navigate to="/preview" replace />} />
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Route>
    </Routes>
  )
}
