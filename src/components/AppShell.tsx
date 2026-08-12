import { useEffect, useRef } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { DocumentBar } from './DocumentBar'
import { StageRail } from './StageRail'
import { Toast } from './Toast'

export function AppShell() {
  const location = useLocation()
  const contentRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0
    document.documentElement.scrollTop = 0
    document.body.scrollTop = 0
  }, [location.pathname])

  return (
    <div className="converter-app">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <div className="app">
        <StageRail />
        <div className="main">
          <DocumentBar />
          <main ref={contentRef} className="content" id="main-content"><Outlet /></main>
        </div>
        <Toast />
      </div>
    </div>
  )
}
