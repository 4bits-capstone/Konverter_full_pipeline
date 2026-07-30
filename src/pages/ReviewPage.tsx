import { Check, ExternalLink, FileText, ImageUp, Pencil, Plus, RotateCcw, Search, Trash2, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ConfidenceBadge } from '../components/ConfidenceBadge'
import { StatusTag } from '../components/StatusTag'
import { publicationService } from '../services'
import { useKonverter } from '../state/KonverterContext'
import type { ReviewItem, ReviewStatus, ReviewTableData, ReviewType } from '../types/konverter'

type StatusFilter = 'all' | ReviewStatus
type LabelFilter = 'all' | ReviewType
type Sort = 'highest' | 'lowest' | 'page'

/* Queue tone, same language as the metadata cards: settled items go plain white,
   anything still owed to the reviewer is tinted by how urgent it is. */
const itemTone = (item: ReviewItem) => {
  if (item.status === 'accepted' || item.status === 'edited' || item.status === 'removed') return 'ok'
  if (item.status === 'needs_attention' || item.band === 'low') return 'alert'
  return 'warn'
}

const structureLabels: Array<{ value: ReviewType; label: string; description: string }> = [
  { value: 'title', label: 'Title', description: 'The single main title of the whole document.' },
  { value: 'chapter_title', label: 'Chapter title', description: 'The title that starts a chapter, appendix group, or equivalent top-level part.' },
  { value: 'section_header_1', label: 'H1', description: 'The chapter heading repeated at the start of the chapter content.' },
  { value: 'section_header_2', label: 'H2', description: 'A chapter section named on that chapter’s opening contents page.' },
  { value: 'section_header_3', label: 'H3', description: 'A styled subsection not listed on the chapter opening page.' },
  { value: 'section_header_4', label: 'H4', description: 'A lower-level heading nested under an H3.' },
  { value: 'section_header_5', label: 'H5', description: 'The fifth level in the document hierarchy.' },
  { value: 'caption', label: 'Caption', description: 'Text identifying or explaining a table, picture, or figure.' },
  { value: 'document_index', label: 'Document index', description: 'A table of contents or document index.' },
  { value: 'footnote', label: 'Footnote', description: 'A note referenced from the main text, usually at the bottom of a page.' },
  { value: 'header', label: 'Header', description: 'Repeated page-header content excluded from the reading flow.' },
  { value: 'footer', label: 'Footer', description: 'Repeated page-footer content excluded from the reading flow.' },
  { value: 'form', label: 'Form', description: 'A group of fields or controls intended for user input.' },
  { value: 'formula', label: 'Formula', description: 'A mathematical or scientific expression.' },
  { value: 'list', label: 'List', description: 'Related items presented in an ordered or unordered sequence.' },
  { value: 'picture', label: 'Picture', description: 'A photograph, illustration, chart, or other embedded image.' },
  { value: 'table', label: 'Table', description: 'Information organised into rows and columns.' },
  { value: 'text', label: 'Text', description: 'A paragraph or other body-text content.' },
  { value: 'unspecified', label: 'Unspecified', description: 'Content whose structure cannot yet be determined.' },
]

function StructureChip({ item }: { item: Pick<ReviewItem, 'type' | 'label'> }) {
  const description = structureLabels.find((label) => label.value === item.type)?.description
  return <span className="typechip structure-chip" data-label={item.type} title={description} tabIndex={0}>{item.label}</span>
}

const emptyTable: ReviewTableData = { headers: ['Column 1'], rows: [['']] }

function cloneTable(table: ReviewTableData): ReviewTableData {
  return {
    headers: [...table.headers],
    rows: table.rows.map((row) => [...row]),
  }
}

function tableToText(table: ReviewTableData): string {
  return [table.headers, ...table.rows]
    .map((row) => row.join(' | '))
    .filter((row) => row.replaceAll('|', '').trim())
    .join('\n')
}

function tableToListText(table: ReviewTableData): string {
  const dataRows = table.rows
    .map((row) => row.map((cell) => cell.trim()).filter(Boolean))
    .filter((row) => row.length)

  const fallbackRows = dataRows.length
    ? dataRows
    : [table.headers.map((header) => header.trim()).filter((header) => header && !/^column \d+$/i.test(header))]

  return fallbackRows
    .filter((row) => row.length)
    .map((row) => row.join(' — '))
    .join('\n')
}

function isGenericHeader(value: string): boolean {
  return !value.trim() || /^column \d+$/i.test(value.trim())
}

function tableToStructuredText(table: ReviewTableData, targetType: ReviewType): string {
  if (targetType === 'list') return tableToListText(table)

  const headers = table.headers.map((value) => value.replaceAll('|', ' ').replace(/\s+/g, ' ').trim())
  const rows = table.rows
    .map((row) => row.map((value) => value.replaceAll('|', ' ').replace(/\s+/g, ' ').trim()))
    .filter((row) => row.some(Boolean))
  const dataRows = rows.length
    ? rows
    : headers.filter((header) => header && !isGenericHeader(header)).map((header) => [header])

  if (targetType === 'form') {
    return dataRows.map((row) => row
      .map((value, index) => value
        ? (!isGenericHeader(headers[index] ?? '') ? `${headers[index]}: ${value}` : value)
        : '')
      .filter(Boolean)
      .join('\n'))
      .filter(Boolean)
      .join('\n\n')
  }

  if (targetType === 'footnote') {
    return dataRows.map((row) => {
      const facts = row
        .map((value, index) => value
          ? (!isGenericHeader(headers[index] ?? '') ? `${headers[index]}: ${value}` : value)
          : '')
        .filter(Boolean)
      return facts.length ? `${facts.join('; ').replace(/\.$/, '')}.` : ''
    })
      .filter(Boolean)
      .join(' ')
  }

  return dataRows
    .map((row) => row.filter(Boolean).join(' — '))
    .filter(Boolean)
    .join('\n')
}

function splitListItems(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:[•\-–*]|\d+[.)])\s*/, '').trim())
    .filter(Boolean)
}

function textToTable(text: string): ReviewTableData {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const rows = lines.map((line) => line.includes('|') ? line.split('|').map((cell) => cell.trim()) : [line])
  const width = Math.max(1, ...rows.map((row) => row.length))
  const normalised = rows.map((row) => [...row, ...Array.from({ length: width - row.length }, () => '')])
  if (normalised.length > 1) return { headers: normalised[0], rows: normalised.slice(1) }
  return { headers: Array.from({ length: width }, (_, index) => `Column ${index + 1}`), rows: normalised.length ? normalised : [Array.from({ length: width }, () => '')] }
}

const usesTableEditor = (type: ReviewType) => type === 'table' || type === 'document_index'

function TableExtract({ table, caption }: { table?: ReviewTableData; caption: string }) {
  if (!table) return <div className="extract-box">No table cells were extracted.</div>

  return (
    <div className="extract-box review-table-scroll" tabIndex={0} role="region" aria-label={`${caption}; scroll horizontally when needed`}>
      <table className="review-table-extract">
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{table.headers.map((header, index) => <th scope="col" key={`${header}-${index}`}>{header}</th>)}</tr></thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {table.headers.map((_, columnIndex) => <td key={`cell-${rowIndex}-${columnIndex}`}>{row[columnIndex] ?? ''}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TableEditor({ table, onChange }: { table: ReviewTableData; onChange: (table: ReviewTableData) => void }) {
  const updateHeader = (columnIndex: number, value: string) => {
    const next = cloneTable(table)
    next.headers[columnIndex] = value
    onChange(next)
  }

  const updateCell = (rowIndex: number, columnIndex: number, value: string) => {
    const next = cloneTable(table)
    next.rows[rowIndex] = next.headers.map((_, index) => next.rows[rowIndex]?.[index] ?? '')
    next.rows[rowIndex][columnIndex] = value
    onChange(next)
  }

  const addColumn = () => {
    onChange({
      headers: [...table.headers, `Column ${table.headers.length + 1}`],
      rows: table.rows.map((row) => [...row, '']),
    })
  }

  const removeColumn = (columnIndex: number) => {
    if (table.headers.length === 1) return
    onChange({
      headers: table.headers.filter((_, index) => index !== columnIndex),
      rows: table.rows.map((row) => row.filter((_, index) => index !== columnIndex)),
    })
  }

  const addRow = () => onChange({ ...table, rows: [...table.rows, table.headers.map(() => '')] })
  const removeRow = (rowIndex: number) => onChange({ ...table, rows: table.rows.filter((_, index) => index !== rowIndex) })

  return (
    <div className="review-table-editor">
      <div className="review-table-editor-head">
        <span>Edit each header or cell directly. Rows and columns can also be added or removed.</span>
        <button className="btn btn-outline btn-sm" type="button" onClick={addColumn}><Plus />Add column</button>
      </div>
      <div className="review-table-scroll" tabIndex={0} role="region" aria-label="Editable corrected table; scroll horizontally when needed">
        <table className="review-table-extract editable-review-table">
          <caption className="sr-only">Editable corrected table</caption>
          <thead>
            <tr>
              {table.headers.map((header, columnIndex) => (
                <th scope="col" key={`header-${columnIndex}`}>
                  <div className="editable-table-header">
                    <input className="input" aria-label={`Header ${columnIndex + 1}`} value={header} onChange={(event) => updateHeader(columnIndex, event.target.value)} />
                    <button className="btn btn-ghost btn-sm icon-button" type="button" disabled={table.headers.length === 1} aria-label={`Remove column ${header || columnIndex + 1}`} onClick={() => removeColumn(columnIndex)}><Trash2 /></button>
                  </div>
                </th>
              ))}
              <th scope="col" className="table-row-actions">Row actions</th>
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr key={`edit-row-${rowIndex}`}>
                {table.headers.map((header, columnIndex) => (
                  <td key={`edit-cell-${rowIndex}-${columnIndex}`}>
                    <textarea
                      className="input"
                      rows={2}
                      aria-label={`Row ${rowIndex + 1}, ${header || `column ${columnIndex + 1}`}`}
                      value={row[columnIndex] ?? ''}
                      onChange={(event) => updateCell(rowIndex, columnIndex, event.target.value)}
                    />
                  </td>
                ))}
                <td className="table-row-actions"><button className="btn btn-ghost btn-sm icon-button" type="button" aria-label={`Remove row ${rowIndex + 1}`} onClick={() => removeRow(rowIndex)}><Trash2 /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button className="btn btn-outline btn-sm" type="button" onClick={addRow}><Plus />Add row</button>
    </div>
  )
}

function ListEditor({ text, onChange }: { text: string; onChange: (text: string) => void }) {
  const editableItems = text
    ? text.split(/\r?\n/).map((line) => line.replace(/^\s*(?:[•\-–*]|\d+[.)])\s*/, '').trim())
    : ['']
  const update = (next: string[]) => onChange(next.join('\n'))

  return (
    <div className="review-list-editor" role="group" aria-label="Editable corrected list">
      <div className="review-list-editor-head">
        <span>Each row becomes one semantic list item. Table headers and column separators are not carried across.</span>
        <button className="btn btn-outline btn-sm" type="button" onClick={() => update([...editableItems, ''])}><Plus />Add item</button>
      </div>
      <ol>
        {editableItems.map((item, index) => (
          <li key={`list-item-${index}`}>
            <span aria-hidden="true">{index + 1}</span>
            <textarea
              className="input"
              rows={2}
              aria-label={`List item ${index + 1}`}
              value={item}
              onChange={(event) => {
                const next = [...editableItems]
                next[index] = event.target.value
                update(next)
              }}
            />
            <button
              className="btn btn-ghost btn-sm icon-button"
              type="button"
              aria-label={`Remove list item ${index + 1}`}
              disabled={editableItems.length === 1}
              onClick={() => update(editableItems.filter((_, itemIndex) => itemIndex !== index))}
            >
              <Trash2 />
            </button>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function ReviewPage() {
  const navigate = useNavigate()
  const {
    activeDocument,
    activeDocumentId,
    completedDocuments,
    runningDocuments,
    selectDocument,
    reviewItems,
    reviewLoading,
    pendingCount,
    setReviewStatus,
    saveReviewItem,
    unlock,
    showToast,
  } = useKonverter()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [labelFilter, setLabelFilter] = useState<LabelFilter>('all')
  const [sort, setSort] = useState<Sort>('highest')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('i1')
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [editType, setEditType] = useState<ReviewType>('text')
  const [editTable, setEditTable] = useState<ReviewTableData>(emptyTable)
  const [uploadedPicture, setUploadedPicture] = useState<string | null>(null)
  const [showDetailMobile, setShowDetailMobile] = useState(false)
  const [evidenceFailed, setEvidenceFailed] = useState(false)

  useEffect(() => {
    unlock('metadata')
  }, [unlock])

  const completedDocumentIds = completedDocuments.map((document) => document.id).join('|')

  useEffect(() => {
    if (completedDocuments.length && !completedDocuments.some((document) => document.id === activeDocumentId)) {
      selectDocument(completedDocuments[0].id)
    }
  }, [activeDocumentId, completedDocumentIds, selectDocument])

  const filteredItems = useMemo(() => {
    let list = [...reviewItems]
    if (statusFilter !== 'all') list = list.filter((item) => item.status === statusFilter)
    if (labelFilter !== 'all') list = list.filter((item) => item.type === labelFilter)
    const normalisedQuery = query.trim().toLowerCase()
    if (normalisedQuery) {
      list = list.filter((item) => [
        item.title,
        item.label,
        item.extractedText,
        item.correctedText,
        item.note,
        ...(item.keyValues?.flat() ?? []),
        ...(item.tableData ? [item.tableData.headers, ...item.tableData.rows].flat() : []),
        ...(item.correctedTable ? [item.correctedTable.headers, ...item.correctedTable.rows].flat() : []),
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalisedQuery)))
    }
    list.sort(sort === 'highest'
      ? (a, b) => b.confidence - a.confidence
      : sort === 'lowest'
        ? (a, b) => a.confidence - b.confidence
        : (a, b) => a.page - b.page)
    return list
  }, [labelFilter, query, reviewItems, sort, statusFilter])

  const selected = filteredItems.find((item) => item.id === selectedId) ?? filteredItems[0]

  useEffect(() => {
    setEvidenceFailed(false)
  }, [activeDocumentId, selected?.id])

  const act = async (item: ReviewItem, status: 'accepted' | 'removed') => {
    await setReviewStatus(item.id, status)
    showToast(status === 'accepted' ? 'Item accepted' : 'Item removed from generated output')
    setEditing(false)
  }

  const beginEdit = (item: ReviewItem) => {
    setEditing(true)
    const table = cloneTable(item.correctedTable ?? item.tableData ?? emptyTable)
    setEditText(item.correctedText ?? item.extractedText ?? tableToText(table))
    setEditType(item.type)
    setEditTable(table)
  }

  const saveEdit = async (item: ReviewItem) => {
    const label = structureLabels.find((entry) => entry.value === editType)?.label ?? editType
    await saveReviewItem(item.id, {
      type: editType,
      label,
      status: 'edited',
      ...(usesTableEditor(editType) ? { correctedTable: editTable } : { correctedText: editText }),
    })
    setEditing(false)
    showToast('Review changes saved')
  }

  const changeEditType = (nextType: ReviewType) => {
    if (usesTableEditor(nextType) && !usesTableEditor(editType)) setEditTable(textToTable(editText))
    if (!usesTableEditor(nextType) && usesTableEditor(editType)) {
      setEditText(tableToStructuredText(editTable, nextType))
    }
    setEditType(nextType)
  }

  const restoreToOutput = async (item: ReviewItem) => {
    await setReviewStatus(item.id, 'accepted')
    showToast('Item restored to generated output')
  }

  const switchReviewDocument = (nextId: string) => {
    if (nextId === activeDocumentId) return
    if (editing && !window.confirm('Switch documents and discard the unsaved changes in this review item?')) return

    const nextDocument = completedDocuments.find((document) => document.id === nextId)
    setEditing(false)
    setSelectedId('')
    setShowDetailMobile(false)
    setEvidenceFailed(false)
    selectDocument(nextId)
    showToast(`Now reviewing ${nextDocument?.fileName ?? 'the selected document'}`)
  }

  const uploadPicture = async (item: ReviewItem, file?: File) => {
    if (!file) return
    setUploadedPicture(file.name)
    await setReviewStatus(item.id, 'edited')
    showToast('Replacement picture uploaded')
  }

  const continueToMetadata = () => {
    unlock('metadata')
    navigate('/metadata')
  }

  return (
    <section className="screen active" aria-labelledby="review-heading">
      <div className="section-title review-titlebar">
        <div>
          <span className="eyebrow">Stage 2 of 5</span>
          <h2 id="review-heading">Review structure flags</h2>
        </div>
        <button className="btn btn-primary btn-sm" onClick={continueToMetadata}>Continue to metadata →</button>
      </div>

      {completedDocuments.length > 0 && (
        <section className="review-document-switcher" aria-labelledby="review-document-heading">
          <div>
            <span className="eyebrow">Ready documents</span>
            <h3 id="review-document-heading">Choose which document to review</h3>
            <p>{completedDocuments.length} completed{runningDocuments.length ? ` · ${runningDocuments.length} still processing in the background` : ''}</p>
            <span className="active-review-document" role="status" aria-live="polite">
              <Check aria-hidden="true" />
              Currently reviewing: <strong>{activeDocument?.fileName ?? completedDocuments[0].fileName}</strong>
            </span>
          </div>
          <label htmlFor="review-document-select">
            Document
            <select
              id="review-document-select"
              className="sel"
              value={completedDocuments.some((document) => document.id === activeDocumentId) ? activeDocumentId ?? '' : completedDocuments[0].id}
              onChange={(event) => switchReviewDocument(event.target.value)}
            >
              {completedDocuments.map((document) => <option key={document.id} value={document.id}>{document.fileName}</option>)}
            </select>
          </label>
          {runningDocuments.length > 0 && <button className="btn btn-outline btn-sm" onClick={() => navigate('/upload')}>View processing queue</button>}
        </section>
      )}

      <details className="review-guidance" open>
        <summary>How to review structure confidence flags</summary>
        <div className="review-guidance-body">
          <div>
            <h3>What the confidence score means</h3>
            <p>The score estimates how certain the AI is about the <b>structure label</b>, such as H2, Table, or Picture. It does not score the accuracy of the extracted wording. A low score needs more attention than a medium score.</p>
            <h3>What you need to check</h3>
            <ol>
              <li>Confirm the structure label is correct; choose the correct label if it is not.</li>
              <li>Check that the extracted text, table, or picture matches the PDF.</li>
              <li>Use <b>Open original page</b> to compare it directly with the source.</li>
            </ol>
          </div>
          <div>
            <h3>Structure label guide</h3>
            <div className="structure-guide" aria-label="Structure label definitions">
              {structureLabels.map((item) => (
                <span key={item.value} className="structure-guide-item" tabIndex={0} title={item.description}>
                  <span className="typechip structure-chip" data-label={item.value}>{item.label}</span>
                  <span className="structure-tooltip" role="tooltip">{item.description}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      </details>

      <div className="toolbar review-toolbar">
        <div className="tb-control search-control">
          <label htmlFor="review-search">Search queue</label>
          <span className="search-input-wrap"><Search aria-hidden="true" /><input id="review-search" className="input" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search labels and extracted text" /></span>
        </div>
        <div className="tb-control">
          <label htmlFor="show-filter">Status</label>
          <select id="show-filter" className="sel" value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value as StatusFilter); setShowDetailMobile(false) }}>
            <option value="all">All items</option>
            <option value="pending">Pending</option>
            <option value="accepted">Accepted</option>
            <option value="edited">Edited</option>
            <option value="removed">Removed from output</option>
          </select>
        </div>
        <div className="tb-control">
          <label htmlFor="label-filter">Filter by structure label</label>
          <select id="label-filter" className="sel" value={labelFilter} onChange={(event) => { setLabelFilter(event.target.value as LabelFilter); setShowDetailMobile(false) }}>
            <option value="all">All labels</option>
            {structureLabels.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </div>
        <div className="tb-control">
          <label htmlFor="sort-filter">Sort</label>
          <select id="sort-filter" className="sel" value={sort} onChange={(event) => setSort(event.target.value as Sort)}>
            <option value="highest">Highest confidence first</option>
            <option value="lowest">Lowest confidence first</option>
            <option value="page">Page order</option>
          </select>
        </div>
        <div className="tb-state">
          <span className={`pill ${pendingCount ? 'warn' : 'ok'}`} aria-live="polite">
            {pendingCount ? <TriangleAlert /> : <Check />}
            {pendingCount ? (
              <span><b className="pill-count">{pendingCount}</b> <span className="pill-label">{pendingCount === 1 ? 'item needs' : 'items need'} review</span></span>
            ) : (
              <span className="pill-label">All {reviewItems.length} items reviewed</span>
            )}
          </span>
        </div>
      </div>

      <p className="mobile-hint">Tap a flagged item to review it.</p>
      <div className={`review-grid ${showDetailMobile ? 'show-detail' : ''}`}>
        <div className="queue">
          <div className="queue-head"><span>Flagged queue</span><span>{filteredItems.length} item{filteredItems.length === 1 ? '' : 's'}</span></div>
          <div className="qlist" role="listbox" aria-label="Flagged items">
            {reviewLoading && <div style={{ padding: 20 }}>Loading review items…</div>}
            {!reviewLoading && filteredItems.length === 0 && <div className="empty-filter">No items match these filters.</div>}
            {filteredItems.map((item) => (
              <button
                key={item.id}
                className={`qitem tone-${itemTone(item)}`}
                role="option"
                aria-selected={selected?.id === item.id}
                aria-current={selected?.id === item.id ? 'true' : undefined}
                onClick={() => { setSelectedId(item.id); setEditing(false); setUploadedPicture(null); setEvidenceFailed(false); setShowDetailMobile(true) }}
              >
                <div className="qitem-top">
                  <StructureChip item={item} />
                  <ConfidenceBadge band={item.band} score={item.confidence} />
                  <span className="pg">p.{item.page}</span>
                </div>
                <div className="qitem-txt">{item.title}</div>
                <div className="qitem-bot"><StatusTag status={item.status} /></div>
              </button>
            ))}
          </div>
        </div>

        <div className="detail">
          {selected ? (
            <>
              <button className="mobile-back" type="button" onClick={() => setShowDetailMobile(false)}>← Back to flagged queue</button>
              <div className="detail-head">
                <StructureChip item={selected} />
                <ConfidenceBadge band={selected.band} score={selected.confidence} />
                <StatusTag status={selected.status} />
                <span className="mono detail-page">page {selected.page}</span>
              </div>
              <div className="detail-body">
                <h3 className="detail-title">{selected.title}</h3>
                {selected.note && <div className="callout"><FileText />{selected.note}</div>}

                <div className="structure-label-editor">
                  <div>
                    <label htmlFor="selected-structure-label">Structure label</label>
                    <span>{editing ? 'Choose the label that best describes this content.' : 'Select Edit below to change this label.'}</span>
                  </div>
                  <select
                    id="selected-structure-label"
                    className="sel"
                    value={editing ? editType : selected.type}
                    disabled={!editing}
                    onChange={(event) => changeEditType(event.target.value as ReviewType)}
                  >
                    {structureLabels.map((item) => <option key={item.value} value={item.value}>{item.label} — {item.description}</option>)}
                  </select>
                </div>

                <div className="field-label">Extracted result (reference only)</div>
                {selected.kind === 'kv' ? (
                  <dl className="kv extract-box">{selected.keyValues?.map(([key, value]) => <div key={key} style={{ display: 'contents' }}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
                ) : selected.kind === 'table' ? <TableExtract table={selected.tableData} caption="Extracted table" /> : (
                  <div className="extract-box pre-wrap">{selected.extractedText || <span style={{ color: 'var(--muted)' }}>No text or image was extracted.</span>}</div>
                )}

                {selected.correctedTable && !editing && (
                  <>
                    <div className="field-label">Saved corrected table</div>
                    <TableExtract table={selected.correctedTable} caption="Saved corrected table" />
                  </>
                )}

                {selected.correctedText && !editing && (
                  <>
                    <div className="field-label">Saved correction</div>
                    {selected.type === 'list' ? (
                      <ul className="corrected-result corrected-list">
                        {splitListItems(selected.correctedText).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
                      </ul>
                    ) : <div className="corrected-result pre-wrap">{selected.correctedText}</div>}
                  </>
                )}

                {editing && (
                  <div className="correction-editor">
                    <div className="field-label">{selected.kind === 'table' ? 'Corrected table' : 'Corrected result'}</div>
                    {usesTableEditor(editType)
                      ? <TableEditor table={editTable} onChange={setEditTable} />
                      : editType === 'list'
                        ? <ListEditor text={editText} onChange={setEditText} />
                        : <textarea className="extract-input" aria-label="Corrected text" rows={4} value={editText} onChange={(event) => setEditText(event.target.value)} autoFocus />}
                    <div className="hint">
                      {usesTableEditor(editType)
                        ? 'This structure is corrected as rows and columns.'
                        : editType === 'list'
                          ? 'Enter one list item per line.'
                          : 'This structure is corrected as text.'}
                    </div>
                  </div>
                )}

                {selected.type === 'picture' && (
                  <div className="manual-picture-upload">
                    <div>
                      <strong>{uploadedPicture ? 'Replacement picture ready' : 'Picture extraction failed'}</strong>
                      <span>{uploadedPicture ?? 'Upload the picture manually if it is missing from the extracted result.'}</span>
                    </div>
                    <label className="btn btn-outline btn-sm" aria-disabled={!editing}>
                      <ImageUp />Upload picture
                      <input className="sr-only" type="file" accept="image/*" disabled={!editing} onChange={(event) => void uploadPicture(selected, event.target.files?.[0])} />
                    </label>
                  </div>
                )}

                <div className="field-label source-label">Where this came from</div>
                <div className="detail-source">
                  <div className="detail-source-head">
                    <FileText />Original PDF evidence
                    <a className="source-page-link" href={publicationService.sourceUrl(activeDocumentId ?? '', selected.source.page)} target="_blank" rel="noreferrer">
                      Open original page <ExternalLink aria-hidden="true" />
                    </a>
                    <span className="mono">p.{selected.source.page}</span>
                  </div>
                  <div className="page-doc source-evidence-preview">
                    {!evidenceFailed ? (
                      <img
                        src={publicationService.evidenceUrl(activeDocumentId ?? '', selected.id)}
                        alt={`Original PDF evidence cropped from page ${selected.source.page}`}
                        loading="lazy"
                        onError={() => setEvidenceFailed(true)}
                      />
                    ) : (
                      <div className="source-evidence-fallback">
                        <TriangleAlert aria-hidden="true" />
                        <span>The visual crop is unavailable. Open the original page to compare the source directly.</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              <div className="actionbar detail-actions">
                {editing ? (
                  <>
                    <button className="btn btn-primary review-save-action" onClick={() => saveEdit(selected)}><Check />Save changes</button>
                    <button className="btn btn-outline" onClick={() => setEditing(false)}>Cancel</button>
                  </>
                ) : (
                  <>
                    <button className="btn btn-outline" disabled={selected.status === 'accepted'} onClick={() => act(selected, 'accepted')}><Check />Accept</button>
                    <button className="btn btn-outline" aria-label="Edit flagged item" onClick={() => beginEdit(selected)}><Pencil />Edit</button>
                    {selected.status === 'removed' ? (
                      <button className="btn btn-outline" onClick={() => restoreToOutput(selected)}><RotateCcw />Restore to output</button>
                    ) : (
                      <button className="btn btn-danger" onClick={() => act(selected, 'removed')}><Trash2 />Remove from output</button>
                    )}
                  </>
                )}
              </div>
            </>
          ) : <div className="detail-body empty-filter">{reviewLoading ? 'Loading the complete review queue and source evidence…' : 'Select a flagged item.'}</div>}
        </div>
      </div>
    </section>
  )
}
