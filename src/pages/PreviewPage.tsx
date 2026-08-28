import { ArrowLeft, Check, ChevronDown, Code2, Download, ExternalLink, FileCheck2, FileJson2, Info, Menu, Network, RotateCcw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { ReportFrame } from '../components/ReportFrame'
import { emptyMetadata } from '../config/workflow'
import { converterStagePath } from '../lib/converterRoutes'
import { formatPublicationDate } from '../lib/publicationFormatting'
import { publicationService } from '../services'
import { useKonverter } from '../state/KonverterContext'

const formats = [
  { type: 'html' as const, label: 'Accessible HTML', description: 'Structured web document', Icon: Code2 },
  { type: 'jsonld' as const, label: 'JSON-LD', description: 'Structured metadata', Icon: FileJson2 },
  { type: 'structured' as const, label: 'Structured JSON', description: 'Reviewed document blocks', Icon: Network },
]

function DownloadMenu({ documentId }: { documentId: string }) {  const [open, setOpen] = useState(false)
  const menu = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const closeOutside = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() }
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])
  return (
    <div className="converter-download-menu" ref={menu} onBlur={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
    }}>
      <button ref={trigger} type="button" className="btn btn-primary converter-download-trigger"
        aria-expanded={open} aria-controls="converted-download-options" onClick={() => setOpen(value => !value)}>
        <Download aria-hidden="true" />Download files<ChevronDown className="converter-download-chevron" aria-hidden="true" />
      </button>
      {open && <div className="converter-download-popover" id="converted-download-options">
        <div className="converter-download-popover-panel" role="group" aria-label="Export formats">
          {formats.map(({ type, label, description, Icon }) => (
            <a key={type} href={publicationService.exportUrl(documentId, type)} onClick={() => setOpen(false)}>
              <Icon aria-hidden="true" /><span><strong>{label}</strong><small>{description}</small></span>
            </a>
          ))}
        </div>
      </div>}
    </div>
  )
}

export function PreviewPage() {
  const navigate = useNavigate()
  const { activeDocument, activeDocumentId, resetWorkflow } = useKonverter()
  const query = useQuery({
    queryKey: ['publication', activeDocumentId ?? 'none'],
    queryFn: () => publicationService.get(activeDocumentId!),
    enabled: Boolean(activeDocumentId),
  })
  const metadata = query.data?.metadata ?? emptyMetadata
  const publication = query.data?.publication
  const reportPath = `/report/${encodeURIComponent(activeDocumentId ?? '')}`

  return (
    <section className="screen active preview-screen" aria-labelledby="preview-heading">
      <div className="section-title preview-titlebar">
        <div>
          <span className="eyebrow">Stage 4 of 4</span>
          <h2 id="preview-heading">Preview converted document</h2>
          <p className="lead">Check the accessible report and download the reviewed output in the format you need.</p>
        </div>
        {publication && <span className="preview-ready"><Check aria-hidden="true" />Ready to export</span>}
      </div>
      {!activeDocumentId ? (
        <div className="banner banner-warn"><Info aria-hidden="true" />Select and approve a document before previewing.</div>
      ) : query.isLoading ? (
        <div className="panel panel-pad workflow-loading" role="status"><span className="spinner" />Loading reviewed document…</div>
      ) : query.isError || !publication ? (
        <div className="banner banner-warn" role="alert"><Info aria-hidden="true" />The reviewed document could not be loaded. <button className="btn btn-outline" onClick={() => query.refetch()}>Try again</button></div>
      ) : (
        <div className="preview-grid preview-grid-single">
          <article className="converter-output-card" aria-labelledby="converter-output-heading">
            <div className="converter-output-summary">
              <span className="converter-output-icon"><FileCheck2 aria-hidden="true" /></span>
              <div>
                <span className="eyebrow">Conversion complete</span>
                <h3 id="converter-output-heading">{metadata.title}</h3>
                <p>{activeDocument?.fileName ?? publication.sourceFile} · {activeDocument?.pages || publication.stats.pages} pages</p>
              </div>
            </div>
            <dl className="converter-output-meta">
              <div><dt>Publisher</dt><dd>{metadata.publisher || 'Not specified'}</dd></div>
              <div><dt>Publication date</dt><dd>{formatPublicationDate(metadata.publishedDate)}</dd></div>
              <div><dt>Jurisdiction</dt><dd>{metadata.jurisdiction || 'Not specified'}</dd></div>
            </dl>
            <div className="converter-output-download-bar" role="group" aria-label="Downloads and report">
              <DownloadMenu key={activeDocumentId} documentId={activeDocumentId} />
              <Link className="converter-source-link" to={reportPath} aria-label="Open report" title="Open report">
                <ExternalLink aria-hidden="true" />
              </Link>
            </div>
          </article>
          <section className="publication-preview-section" aria-labelledby="publication-preview-heading">
            <h3 className="sr-only" id="publication-preview-heading">Accessible publication preview</h3>
            <div className="published publication-preview-shell">
              <div className="pub-browser">
                <Menu className="pub-browser-menu" aria-hidden="true" />
                <Link className="pub-url" to={reportPath} aria-label="Open the accessible publication preview"><span>{reportPath}</span></Link>
              </div>
              <ReportFrame documentId={activeDocumentId} title={`Accessible publication preview: ${metadata.title}`} className="publication-preview-frame" />
            </div>
          </section>
        </div>
      )}
      <nav className="preview-workflow-actions" aria-label="Preview navigation">
        <Link className="btn btn-outline btn-sm" to={converterStagePath('review')}><ArrowLeft aria-hidden="true" />Return to review</Link>
        <button className="btn btn-outline btn-sm" onClick={() => { resetWorkflow(); navigate(converterStagePath('upload')) }}><RotateCcw aria-hidden="true" />Start new upload</button>
      </nav>
    </section>
  )
}
