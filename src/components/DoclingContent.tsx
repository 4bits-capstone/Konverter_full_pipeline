import { FileImage } from 'lucide-react'
import type {
  DoclingBlock,
  DoclingFootnote,
  DoclingHeadingBlock,
  DoclingTableCell,
} from '../lib/docling'

function Heading({ block }: { block: DoclingHeadingBlock }) {
  // The reader's chapter title is its single H1, so resolved H1/H2 content
  // both begin at the accessible H2 level rather than falling through to H6.
  if (block.level <= 2) return <h2 id={block.id}>{block.text}</h2>
  if (block.level === 3) return <h3 id={block.id}>{block.text}</h3>
  if (block.level === 4) return <h4 id={block.id}>{block.text}</h4>
  if (block.level === 5) return <h5 id={block.id}>{block.text}</h5>
  return <h6 id={block.id}>{block.text}</h6>
}

function TableCell({ cell }: { cell: DoclingTableCell }) {
  const props = {
    rowSpan: cell.rowSpan > 1 ? cell.rowSpan : undefined,
    colSpan: cell.colSpan > 1 ? cell.colSpan : undefined,
  }

  if (cell.columnHeader) return <th scope="col" {...props}>{cell.text}</th>
  if (cell.rowHeader) return <th scope="row" {...props}>{cell.text}</th>
  return <td {...props}>{cell.text}</td>
}

function NumberedParagraph({ number, text }: { number?: string; text: string }) {
  return (
    <div className="reader-numbered-paragraph">
      <span className="reader-paragraph-number" aria-hidden="true">{number}</span>
      <p>
        {number ? <span className="sr-only">Paragraph {number}. </span> : null}
        {text}
      </p>
    </div>
  )
}

type ListTreeNode = {
  text: string
  marker?: string
  ordered: boolean
  value?: number
  children: ListTreeNode[]
}

function buildListTree(
  items: Array<{
    text: string
    marker?: string
    level?: number
    ordered?: boolean
    value?: number
  }>,
  defaultOrdered: boolean,
): ListTreeNode[] {
  if (!items.length) return []
  const levels = items.map((item) => Math.max(0, item.level ?? 0))
  const baseLevel = Math.min(...levels)
  const roots: ListTreeNode[] = []
  const stack: Array<{ level: number; children: ListTreeNode[] }> = [{ level: -1, children: roots }]
  items.forEach((item, index) => {
    let level = levels[index] - baseLevel
    while (stack.at(-1)!.level >= level) stack.pop()
    if (level > stack.at(-1)!.level + 1) level = stack.at(-1)!.level + 1
    const node: ListTreeNode = {
      text: item.text,
      marker: item.marker,
      ordered: item.ordered ?? defaultOrdered,
      value: item.value,
      children: [],
    }
    stack.at(-1)!.children.push(node)
    stack.push({ level, children: node.children })
  })
  return roots
}

function NestedList({ nodes, start }: { nodes: ListTreeNode[]; start?: number }) {
  const groups: ListTreeNode[][] = []
  nodes.forEach((node) => {
    const group = groups.at(-1)
    if (!group || group[0].ordered !== node.ordered) groups.push([node])
    else group.push(node)
  })
  return <>{groups.map((group, groupIndex) => {
    const items = group.map((item, index) => (
      <li
        value={item.ordered ? item.value : undefined}
        key={`${item.text}-${index}`}
      >
        {item.text}
        {item.children.length ? <NestedList nodes={item.children} /> : null}
      </li>
    ))
    return group[0].ordered
      ? <ol className="reader-source-list" start={groupIndex === 0 ? start : undefined} key={`ordered-${groupIndex}`}>{items}</ol>
      : <ul className="reader-source-list" key={`unordered-${groupIndex}`}>{items}</ul>
  })}</>
}

function ContentBlock({
  block,
  figureUrl,
}: {
  block: DoclingBlock
  figureUrl?: (imageKey: string) => string
}) {
  if (block.type === 'heading') return <Heading block={block} />

  if (block.type === 'paragraph') {
    return block.number
      ? <NumberedParagraph number={block.number} text={block.text} />
      : <p className="docling-paragraph">{block.text}</p>
  }

  if (block.type === 'list') {
    if (block.style === 'numbered-paragraphs') {
      return (
        <div className="docling-numbered-group">
          {block.items.map((item, index) => (
            <NumberedParagraph number={item.marker} text={item.text} key={`${item.marker}-${index}`} />
          ))}
        </div>
      )
    }

    const numberedItems = block.items.map((item) => item.text.match(/^(\d+(?:\.\d+)+)\s+(.+)$/s))
    if (numberedItems.some(Boolean)) {
      return (
        <div className="docling-numbered-group">
          {block.items.map((item, index) => {
            const numbered = numberedItems[index]
            return numbered
              ? <NumberedParagraph number={numbered[1]} text={numbered[2]} key={`${numbered[1]}-${index}`} />
              : <ul className="reader-source-list" key={`${item.text}-${index}`}><li>{item.text}</li></ul>
          })}
        </div>
      )
    }

    return (
      <NestedList
        nodes={buildListTree(block.items, block.style === 'ordered')}
        start={block.start}
      />
    )
  }

  if (block.type === 'box_section') {
    const titleId = `${block.id}-title`
    return (
      <section
        className={`docling-box-section docling-box-section--${block.variant}`}
        aria-labelledby={titleId}
      >
        <h3 id={titleId}>{block.title}</h3>
        <div className="docling-box-section-content">
          {block.blocks.map((child, index) => (
            <ContentBlock
              block={child}
              figureUrl={figureUrl}
              key={`${child.type}-${index}`}
            />
          ))}
        </div>
      </section>
    )
  }

  if (block.type === 'table') {
    const caption = block.caption?.trim()
    return (
      <div className="docling-table-scroll" tabIndex={0} role="region" aria-label={`${caption || 'Table'}; scroll horizontally when needed`}>
        <table id={block.id} className="docling-table">
          {caption ? <caption>{caption}</caption> : null}
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={`${block.id}-row-${rowIndex}`}>
                {row.map((cell, cellIndex) => <TableCell cell={cell} key={`${rowIndex}-${cell.startColumn}-${cellIndex}`} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (block.type === 'figure') {
    const imageUrl = block.imageKey && figureUrl ? figureUrl(block.imageKey) : undefined
    return (
      <figure className="docling-figure" id={block.id}>
        {imageUrl ? (
          <img className="docling-figure-image" src={imageUrl} alt={block.caption || 'Document figure'} loading="lazy" />
        ) : (
          <div className="docling-figure-placeholder" role="img" aria-label={block.caption}>
            <FileImage aria-hidden="true" />
            <span>The original figure preview is unavailable.</span>
          </div>
        )}
        <figcaption>{block.caption}</figcaption>
      </figure>
    )
  }

  if (block.type === 'caption') return <p className="docling-caption">{block.text}</p>

  if (block.type === 'formula') {
    return <div className="docling-formula" role="math" aria-label="Formula">{block.text}</div>
  }

  if (block.type === 'footnote') {
    return <p className="docling-footnote" id={block.id} role="doc-footnote">{block.text}</p>
  }

  if (block.type === 'checkbox') {
    return (
      <label className="docling-checkbox">
        <input type="checkbox" checked={block.checked} readOnly />
        <span>{block.text}</span>
      </label>
    )
  }

  return (
    <fieldset className="docling-group">
      <legend>{block.label}</legend>
      {block.items.map((item, index) => item.checked === undefined
        ? <p key={`${item.text}-${index}`}>{item.text}</p>
        : (
          <label className="docling-checkbox" key={`${item.text}-${index}`}>
            <input type="checkbox" checked={item.checked} readOnly />
            <span>{item.text}</span>
          </label>
        ))}
    </fieldset>
  )
}

export function DoclingContent({
  blocks,
  footnotes,
  figureUrl,
}: {
  blocks: DoclingBlock[]
  footnotes: DoclingFootnote[]
  figureUrl?: (imageKey: string) => string
}) {
  return (
    <>
      <div className="docling-content-blocks">
        {blocks.map((block, index) => <ContentBlock block={block} figureUrl={figureUrl} key={`${block.type}-${index}`} />)}
      </div>

      {footnotes.length ? (
        <details className="reader-footnotes">
          <summary>References and footnotes ({footnotes.length})</summary>
          <ol>
            {footnotes.map((footnote) => (
              <li id={footnote.id} key={footnote.id}>
                {footnote.text}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </>
  )
}
