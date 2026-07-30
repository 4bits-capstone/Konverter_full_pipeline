import { CheckCircle2, Clock3, FilePlus2, FileUp, Play, RefreshCcw, Square, Trash2 } from 'lucide-react'
import { useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { processingSteps } from '../config/workflow'
import { documentService } from '../services'
import { useKonverter } from '../state/KonverterContext'
import type { DocumentProcessingJob } from '../types/konverter'

const MAX_DOCUMENTS = 5

function formatRemainingTime(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  if (hours) return `${hours} hr ${minutes} min ${remainder} sec`
  if (minutes) return `${minutes} min ${remainder} sec`
  return `${remainder} sec`
}

function JobStatus({ job }: { job: DocumentProcessingJob }) {
  if (job.state === 'complete') return <span className="job-status ready"><CheckCircle2 />Ready to review</span>
  if (job.state === 'running') return <span className="job-status running"><span className="spinner" />Processing</span>
  if (job.state === 'failed') return <span className="job-status failed">Needs retry</span>
  return <span className="job-status queued">Queued</span>
}

export function UploadPage() {
  const navigate = useNavigate()
  const {
    documents,
    activeDocument,
    activeDocumentId,
    addDocuments,
    removeDocument,
    selectDocument,
    documentProcessing,
    completedDocuments,
    runningDocuments,
    startDocumentProcessing,
    stopDocumentProcessing,
    showToast,
  } = useKonverter()
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const chooseFiles = () => fileInputRef.current?.click()

  const acceptFiles = (files: FileList | File[]) => {
    const selectedPdfs = Array.from(files).filter((file) => file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'))
    if (!selectedPdfs.length) {
      showToast('Choose one or more PDF documents')
      return
    }
    const remainingSlots = MAX_DOCUMENTS - documents.length
    if (remainingSlots <= 0) {
      showToast(`Remove a document before adding another. The limit is ${MAX_DOCUMENTS}.`)
      return
    }
    const pdfs = selectedPdfs.slice(0, remainingSlots)
    const limitNote = selectedPdfs.length > remainingSlots
      ? ` Only ${remainingSlots} were added because the limit is ${MAX_DOCUMENTS}.`
      : ''
    showToast(`Uploading ${pdfs.length} document${pdfs.length === 1 ? '' : 's'}…`)
    void documentService.uploadDocuments(pdfs)
      .then((uploadedDocuments) => {
        addDocuments(uploadedDocuments)
        showToast(`${uploadedDocuments.length} document${uploadedDocuments.length === 1 ? '' : 's'} added to the processing queue.${limitNote}`)
      })
      .catch((error: unknown) => showToast(error instanceof Error ? error.message : 'Document upload failed'))
  }

  const queuedDocuments = documents.filter((document) => {
    const state = documentProcessing[document.id]?.state ?? 'idle'
    return state === 'idle' || state === 'failed'
  })
  const selectedJob = activeDocument ? documentProcessing[activeDocument.id] : undefined

  const processAllQueued = () => {
    queuedDocuments.forEach((document) => startDocumentProcessing(document.id))
    showToast(`${queuedDocuments.length} document${queuedDocuments.length === 1 ? '' : 's'} started processing`)
  }

  const reviewDocument = (id: string) => {
    selectDocument(id)
    navigate('/review')
  }

  return (
    <section className="screen active" aria-labelledby="upload-heading">
      <div className="upload-wrap upload-wrap-wide">
        <span className="eyebrow">Stage 1 of 5</span>
        <h2 id="upload-heading" style={{ fontSize: 26, marginTop: 8 }}>Upload documents</h2>
        <p className="lead">Add one or more legal or policy PDFs. Documents process independently, so you can review the first completed document while the remaining jobs continue in the background.</p>

        <input
          ref={fileInputRef}
          className="sr-only"
          type="file"
          accept="application/pdf,.pdf"
          multiple
          onChange={(event) => {
            if (event.target.files?.length) acceptFiles(event.target.files)
            event.target.value = ''
          }}
        />

        {!documents.length ? (
            <div
              className="dropzone"
              role="button"
              tabIndex={0}
              aria-label="Upload area. Activate to choose one or more PDFs, or drop files here."
              onClick={chooseFiles}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  chooseFiles()
                }
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                if (event.dataTransfer.files.length) acceptFiles(event.dataTransfer.files)
              }}
            >
              <div className="dz-ic" aria-hidden="true"><FileUp /></div>
              <h3>Drag &amp; drop your documents here</h3>
              <p className="dz-hint">or <span style={{ color: 'var(--accent)', fontWeight: 600, textDecoration: 'underline' }}>choose PDF files</span> from your computer</p>
              <p className="dz-hint"><span className="mono">PDF only</span> · up to 200 MB per file · maximum 5 documents</p>
            </div>
        ) : (
          <>
            <div className="processing-queue-toolbar">
              <div>
                <h3>Processing queue</h3>
                <div className="queue-counts" aria-live="polite">
                  <span>{documents.length} total</span>
                  <span>{runningDocuments.length} processing</span>
                  <span className="ready-count">{completedDocuments.length} ready</span>
                </div>
              </div>
              <div className="processing-queue-actions">
                <button className="btn btn-outline btn-sm" type="button" onClick={chooseFiles}><FilePlus2 />Add documents</button>
                <button className="btn btn-primary btn-sm" type="button" disabled={!queuedDocuments.length} onClick={processAllQueued}><Play />Process all queued</button>
              </div>
            </div>

            {completedDocuments.length > 0 && (
              <div className="banner banner-ok ready-documents-banner">
                <CheckCircle2 />
                <div>
                  <b>{completedDocuments.length} document{completedDocuments.length === 1 ? ' is' : 's are'} ready to review.</b>
                  {completedDocuments.length > 1
                    ? ' Select a completed document below, then open its review queue.'
                    : ' You can review it now while other documents continue processing.'}
                </div>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={selectedJob?.state !== 'complete'}
                  onClick={() => activeDocument && reviewDocument(activeDocument.id)}
                >Review selected document</button>
              </div>
            )}

            <div className="concurrent-document-list" role="radiogroup" aria-label="Choose document to review">
              {documents.map((document) => {
                const job = documentProcessing[document.id] ?? {
                  state: 'idle', startedAt: null, durationMs: 6000, currentStep: 0, progress: 0, remainingSeconds: 0,
                }
                const step = processingSteps[job.currentStep]
                return (
                  <article className={`concurrent-document-card ${activeDocumentId === document.id ? 'selected' : ''}`} key={document.id}>
                    <label className="concurrent-document-main">
                      <input
                        type="radio"
                        name="active-document"
                        value={document.id}
                        checked={activeDocumentId === document.id}
                        onChange={() => selectDocument(document.id)}
                      />
                      <span className="file-ic" aria-hidden="true">PDF</span>
                      <span className="file-meta">
                        <span className="file-name">{document.fileName}</span>
                        <div></div>
                        <span className="file-sub"><span className="mono">{document.sizeLabel ?? '4.7 MB'}</span> · {document.pages ? <span className="mono">{document.pages} pages</span> : 'page count after processing'}</span>
                      </span>
                    </label>
                    <div className="concurrent-job-state">
                      <div className="job-state-line">
                        <JobStatus job={job} />
                        {job.state === 'running' && <span className="job-time"><Clock3 />About {formatRemainingTime(job.remainingSeconds)}</span>}
                      </div>
                      <div className="job-progress" aria-label={`${document.fileName} ${job.progress}% processed`}>
                        <span style={{ width: `${job.progress}%` }} />
                      </div>
                      <span className="job-step">
                        {job.state === 'running'
                          ? job.message ?? `${step?.label ?? 'Processing'}${step?.detail ? ` — ${step.detail}` : ''}`
                          : job.state === 'failed'
                            ? job.message ?? 'Processing failed. Check the backend terminal, then retry.'
                            : job.state === 'complete' ? 'Processing complete' : 'Ready to start'}
                      </span>
                    </div>
                    <div className="concurrent-document-actions">
                      {(job.state === 'idle' || job.state === 'failed') && <button className="btn btn-primary btn-sm" onClick={() => startDocumentProcessing(document.id)}><Play />Start</button>}
                      {job.state === 'running' && <button className="btn btn-danger btn-sm" onClick={() => stopDocumentProcessing(document.id)}><Square />Stop</button>}
                      {job.state === 'complete' && <button className="btn btn-primary btn-sm" onClick={() => reviewDocument(document.id)}>Review now</button>}
                      <button className="btn btn-ghost btn-sm document-remove" type="button" aria-label={`Remove ${document.fileName}`} disabled={job.state === 'running'} onClick={() => removeDocument(document.id)}><Trash2 /></button>
                    </div>
                  </article>
                )
              })}
            </div>

            <div className="processing-queue-footer">
              <button className="btn btn-outline" onClick={chooseFiles}><RefreshCcw />Re-upload or add more documents</button>
              <span>Processing jobs continue if you open a completed document for review.</span>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
