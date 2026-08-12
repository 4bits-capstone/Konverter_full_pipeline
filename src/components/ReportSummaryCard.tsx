import { ShieldCheck } from 'lucide-react'
import type { MouseEventHandler, ReactNode, Ref } from 'react'
import { Link } from 'react-router-dom'

export interface ReportSummaryRecord {
  title: string
  reportNumber: string
  pageCount: number
  publisher: string
  publishedDate: string
  currentAsOf: string
  jurisdiction: string
  status: string
  summary: string
  citation: string
  topics: string[]
  coverUrl: string
  localPdfUrl: string
}

interface ReportSummaryCardProps {
  report: ReportSummaryRecord
  root?: 'article' | 'header'
  headingLevel?: 1 | 2
  headingId?: string
  headingRef?: Ref<HTMLHeadingElement>
  headingTabIndex?: number
  overviewPath?: string
  onCoverClick?: MouseEventHandler<HTMLAnchorElement>
  onTitleClick?: MouseEventHandler<HTMLAnchorElement>
  actions: ReactNode
  className?: string
}

export function ReportSummaryCard({
  report,
  root = 'article',
  headingLevel = 2,
  headingId,
  headingRef,
  headingTabIndex,
  overviewPath,
  onCoverClick,
  onTitleClick,
  actions,
  className,
}: ReportSummaryCardProps) {
  const Root = root
  const Heading = headingLevel === 1 ? 'h1' : 'h2'
  const rootClassName = className ? `report-card ${className}` : 'report-card'
  const cover = <img src={report.coverUrl} alt={`Cover of ${report.title}`} />

  return (
    <Root className={rootClassName} aria-labelledby={headingId}>
      {overviewPath ? (
        <Link className="report-cover-link" to={overviewPath} onClick={onCoverClick}>{cover}</Link>
      ) : (
        <div className="report-cover-link">{cover}</div>
      )}
      <div className="report-card-content">
        <div className="report-card-status-row">
          <span className="official-source-badge"><ShieldCheck aria-hidden="true" /> Reviewed source</span>
          <span>{report.status}</span>
        </div>
        <Heading className="report-card-title" id={headingId} ref={headingRef} tabIndex={headingTabIndex}>
          {overviewPath ? <Link to={overviewPath} onClick={onTitleClick}>{report.title}</Link> : report.title}
        </Heading>
        <p className="report-publisher">{report.publisher}</p>
        <p className="report-summary">{report.summary}</p>
        <dl className="report-card-meta">
          <div><dt>Published</dt><dd>{report.publishedDate}</dd></div>
          <div><dt>Length</dt><dd>{report.pageCount} pages</dd></div>
          <div><dt>Jurisdiction</dt><dd>{report.jurisdiction || 'Not specified'}</dd></div>
        </dl>
        <ul className="topic-list" aria-label="Report topics">
          {report.topics.map((topic) => <li key={topic}>{topic}</li>)}
        </ul>
        <div className="report-card-actions" aria-label={`Ways to use ${report.title}`}>{actions}</div>
      </div>
    </Root>
  )
}
