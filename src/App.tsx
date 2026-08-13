import { lazy, Suspense } from 'react'
import AuthGate from './components/AuthGate'

const ConverterApp = lazy(() => import('./ConverterApp'))

function LoadingPage() {
  return <div className="page-loading" role="status">Loading…</div>
}

export default function App() {
  return (
    <AuthGate>
      <Suspense fallback={<LoadingPage />}><ConverterApp /></Suspense>
    </AuthGate>
  )
}
