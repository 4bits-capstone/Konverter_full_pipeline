import { lazy, Suspense } from 'react'

const ConverterApp = lazy(() => import('./ConverterApp'))

function LoadingPage() {
  return <div className="page-loading" role="status">Loading…</div>
}

export default function App() {
  return <Suspense fallback={<LoadingPage />}><ConverterApp /></Suspense>
}
