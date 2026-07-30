import { Outlet } from 'react-router-dom'
import { DocumentBar } from './DocumentBar'
import { StageRail } from './StageRail'
import { Toast } from './Toast'

export function AppShell() {
  return (
    <>
      <a
        className="fixed top-2 left-2 z-[999] -translate-y-[160%] rounded-md border-2 border-brand-blue bg-white px-3 py-2 font-semibold text-brand-blue no-underline focus:translate-y-0"
        href="#main-content"
      >
        Skip to main content
      </a>
      <div className="grid h-dvh min-h-0 grid-cols-[248px_1fr] overflow-hidden max-[820px]:h-auto max-[820px]:min-h-screen max-[820px]:grid-cols-1 max-[820px]:overflow-visible">
        <StageRail />
        <div className="col-start-2 flex h-dvh min-h-0 min-w-0 flex-col max-[820px]:col-start-1 max-[820px]:h-auto">
          <DocumentBar />
          <main
            className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain p-7 max-[820px]:overflow-visible max-[820px]:p-4"
            id="main-content"
          >
            <Outlet />
          </main>
        </div>
        <Toast />
      </div>
    </>
  )
}
