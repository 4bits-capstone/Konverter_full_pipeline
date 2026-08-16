import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import { converterStagePath } from '../lib/converterRoutes'
import { documentService } from '../services'

export function DocumentListPage() {
  const { data: documents = [], isLoading, isError } = useQuery({
    queryKey: ['documents', 'all'],
    queryFn: () => documentService.listAllDocuments(),
  })

  return (
    <section className="screen active" aria-labelledby="doc-list-heading">
      <div className="admin-page-header">
        <Link className="btn btn-ghost btn-sm" to={converterStagePath('upload')} aria-label="Back to converter">
          <ArrowLeft aria-hidden="true" />
        </Link>
        <div>
          <span className="eyebrow">Admin only</span>
          <h2 id="doc-list-heading">Doc list</h2>
          <p className="lead">Every document uploaded by every user, regardless of ownership.</p>
        </div>
      </div>

      <div className="panel panel-pad">
        {isLoading ? (
          <div className="page-loading" role="status">Loading documents…</div>
        ) : isError ? (
          <div className="banner banner-err" role="alert">The document list could not be loaded.</div>
        ) : documents.length === 0 ? (
          <p className="hint">No documents yet.</p>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <caption className="sr-only">Document list</caption>
              <thead>
                <tr>
                  <th scope="col">Title</th>
                  <th scope="col">File</th>
                  <th scope="col">Pages</th>
                  <th scope="col">Uploaded by</th>
                  <th scope="col">Status</th>
                  <th scope="col">Approved</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((document) => (
                  <tr key={document.id}>
                    <td>{document.title}</td>
                    <td className="mono">{document.fileName}</td>
                    <td>{document.pages}</td>
                    <td>{document.uploadedByEmail ?? '—'}</td>
                    <td>{document.processingState ?? 'idle'}</td>
                    <td>{document.approvedAt ? 'Yes' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
