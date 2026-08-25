import { useEffect, useRef } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { DocumentBar } from './DocumentBar'
import { StageRail } from './StageRail'
import { Toast } from './Toast'

export function AppShell() {
  const location = useLocation()
  const appRef = useRef<HTMLDivElement | null>(null)
  const contentRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0
    document.documentElement.scrollTop = 0
    document.body.scrollTop = 0
  }, [location.pathname])

  useEffect(() => {
    const app = appRef.current
    const content = contentRef.current
    if (!app || !content) return

    const updateScrollbarWidth = () => {
      const scrollbarWidth = Math.max(0, content.offsetWidth - content.clientWidth)
      app.style.setProperty('--workspace-scrollbar-width', `${scrollbarWidth}px`)
    }

    updateScrollbarWidth()
    window.addEventListener('resize', updateScrollbarWidth)

    const resizeObserver = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(updateScrollbarWidth)
    resizeObserver?.observe(content)

    return () => {
      window.removeEventListener('resize', updateScrollbarWidth)
      resizeObserver?.disconnect()
    }
  }, [])

  return (
    <div className="converter-app">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <div className="app" ref={appRef}>
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
