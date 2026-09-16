import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { DocumentChat } from '../components/DocumentChat'
import { ReportFrame } from '../components/ReportFrame'
import { converterStagePath } from '../lib/converterRoutes'
import { publicationService } from '../services'

export function ReportPage() {
  const { documentId = '' } = useParams()
  const publication = useQuery({ queryKey: ['publication', documentId], queryFn: () => publicationService.get(documentId), enabled: Boolean(documentId) })
  const title = publication.data?.metadata.title || 'Reviewed report'

  useEffect(() => {
    if (!publication.data?.jsonLd) return
    const script = document.createElement('script')
    script.id = 'konverter-publication-json-ld'
    script.type = 'application/ld+json'
    script.textContent = JSON.stringify(publication.data.jsonLd).replaceAll('<', '\\u003c')
    document.head.appendChild(script)
    const previousTitle = document.title
    document.title = title
    return () => { script.remove(); document.title = previousTitle }
  }, [publication.data?.jsonLd, title])

  return (
    <main className="converter-app report-page">
      <nav className="report-toolbar" aria-label="Report navigation">
        <Link to={converterStagePath('preview')}><ArrowLeft aria-hidden="true" />Back to preview</Link>
        <span>{title}</span>
      </nav>
      <ReportFrame documentId={documentId} title={title} className="report-frame" hasExternalChat />
      {publication.data && <DocumentChat documentId={documentId} />}
    </main>
  )
}
