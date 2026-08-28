import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { runtimeConfig } from '../config/runtime'
import { publicationService } from '../services'

/** Preview and Open report display the same generated, isolated publication. */
export function ReportFrame({ documentId, title, className, hasExternalChat = false }: {
  documentId: string
  title: string
  className: string
  hasExternalChat?: boolean
}) {
  const report = useQuery({
    queryKey: ['report-html', documentId],
    queryFn: () => publicationService.getHtml(documentId),
    enabled: Boolean(documentId),
  })
  const source = useMemo(() => {
    if (!report.data) return ''
    const parsed = new DOMParser().parseFromString(report.data, 'text/html')
    const base = parsed.createElement('base')
    base.href = new URL(runtimeConfig.apiBaseUrl, window.location.href).origin + '/'
    parsed.head.prepend(base)
    parsed.querySelectorAll('[data-konverter-chat]').forEach(node => node.remove())
    if (hasExternalChat) parsed.querySelector('[data-konverter-publication]')?.setAttribute('data-report-chat', '')
    return '<!doctype html>\n' + parsed.documentElement.outerHTML
  }, [report.data, hasExternalChat])

  if (report.isLoading) return <p role="status" className="report-message">Loading report…</p>
  if (report.isError) return (
    <div role="alert" className="report-message">
      <p>The report could not be loaded. It must be approved before it can be opened.</p>
      <button className="btn btn-outline" onClick={() => report.refetch()}>Try again</button>
    </div>
  )
  return source ? <iframe className={className} title={title} srcDoc={source} sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads" /> : null
}
