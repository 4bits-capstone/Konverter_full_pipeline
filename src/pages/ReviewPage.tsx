import {
  Check,
  ChevronDown,
  CircleHelp,
  ExternalLink,
  FileText,
  ImageUp,
  LoaderCircle,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import {
  type MouseEvent as ReactMouseEvent,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { StatusTag } from "../components/StatusTag";
import { documentService, publicationService } from "../services";
import { useKonverter } from "../state/KonverterContext";
import { converterStagePath } from "../lib/converterRoutes";
import type {
  ReviewItem,
  ReviewStatus,
  ReviewTableData,
  ReviewType,
} from "../types/konverter";

type StatusFilter = "all" | ReviewStatus;
type LabelFilter = "all" | ReviewType;
type Sort = "highest" | "lowest" | "page";
type BulkAction = "accept" | "remove" | "label";
type PendingConfirmation =
  | {
      kind: "bulk";
      ids: string[];
      action: BulkAction;
      selectedType: ReviewType;
      selectedLabel: string;
      message: string;
    }
  | { kind: "switch-document"; nextId: string; message: string };

const itemTone = (item: ReviewItem) => {
  if (
    item.status === "accepted" ||
    item.status === "edited" ||
    item.status === "removed"
  )
    return "ok";
  if (item.status === "needs_attention" || item.band === "low") return "alert";
  return "warn";
};

const structureLabels: Array<{
  value: ReviewType;
  label: string;
  description: string;
  shortMeaning: string;
}> = [
  {
    value: "title",
    label: "Title",
    description: "The single main title of the whole document.",
    shortMeaning: "Main title of the document.",
  },
  {
    value: "section_header_1",
    label: "H1",
    description:
      "A top-level printed-contents entry. Numbered chapters are collapsible; front and back matter are direct links.",
    shortMeaning: "Main chapter or top-level section.",
  },
  {
    value: "section_header_2",
    label: "H2",
    description: "A printed-contents entry nested under the current H1.",
    shortMeaning: "Section within the current H1.",
  },
  {
    value: "section_header_3",
    label: "H3",
    description: "A body subsection below the H1/H2 navigation level.",
    shortMeaning: "Subsection within an H2.",
  },
  {
    value: "section_header_4",
    label: "H4",
    description: "A lower-level heading nested under an H3.",
    shortMeaning: "Subsection within an H3.",
  },
  {
    value: "section_header_5",
    label: "H5",
    description: "The fifth level in the document hierarchy.",
    shortMeaning: "Lowest heading level.",
  },
  {
    value: "caption",
    label: "Caption",
    description: "Text identifying or explaining a table, picture, or figure.",
    shortMeaning: "Description for a table or image.",
  },
  {
    value: "box_section",
    label: "Box Section",
    description:
      "A bounded section that preserves its own paragraphs, lists, tables, figures and other child elements.",
    shortMeaning: "Grouped callout or highlighted content.",
  },
  {
    value: "document_index",
    label: "Document index",
    description: "A table of contents or document index.",
    shortMeaning: "Contents or index listing.",
  },
  {
    value: "footnote",
    label: "Footnote",
    description:
      "A note referenced from the main text, usually at the bottom of a page.",
    shortMeaning: "Reference note outside the main text.",
  },
  {
    value: "header",
    label: "Header",
    description: "Repeated page-header content excluded from the reading flow.",
    shortMeaning: "Repeated content at the page top.",
  },
  {
    value: "footer",
    label: "Footer",
    description: "Repeated page-footer content excluded from the reading flow.",
    shortMeaning: "Repeated content at the page bottom.",
  },
  {
    value: "form",
    label: "Form",
    description: "A group of fields or controls intended for user input.",
    shortMeaning: "Fields or controls for user input.",
  },
  {
    value: "formula",
    label: "Formula",
    description: "A mathematical or scientific expression.",
    shortMeaning: "Mathematical or scientific expression.",
  },
  {
    value: "list",
    label: "List",
    description: "Related items presented in an ordered or unordered sequence.",
    shortMeaning: "Ordered or unordered sequence of items.",
  },
  {
    value: "picture",
    label: "Picture",
    description: "A photograph, illustration, chart, or other embedded image.",
    shortMeaning: "Photograph, chart, or illustration.",
  },
  {
    value: "table",
    label: "Table",
    description: "Information organised into rows and columns.",
    shortMeaning: "Information in rows and columns.",
  },
  {
    value: "text",
    label: "Text",
    description: "A paragraph or other body-text content.",
    shortMeaning: "Paragraph or body-text content.",
  },
  {
    value: "unspecified",
    label: "Unspecified",
    description: "Content whose structure cannot yet be determined.",
    shortMeaning: "Structure not yet identified.",
  },
];

function StructureChip({ item }: { item: Pick<ReviewItem, "type" | "label"> }) {
  const description = structureLabels.find(
    (label) => label.value === item.type,
  )?.description;
  return (
    <span
      className="typechip structure-chip"
      data-label={item.type}
      title={description}
      tabIndex={0}
    >
      {item.label}
    </span>
  );
}

interface StructureTooltipPosition {
  left: number;
  top: number;
  placement: "above" | "below";
}

function getStructureTooltipPosition(
  trigger: HTMLElement,
): StructureTooltipPosition {
  const rect = trigger.getBoundingClientRect();
  const viewportGap = 12;
  const tooltipGap = 8;
  const tooltipWidth = Math.min(
    280,
    Math.max(0, window.innerWidth - viewportGap * 2),
  );
  const desiredLeft = rect.left + rect.width / 2 - tooltipWidth / 2;
  const maximumLeft = Math.max(
    viewportGap,
    window.innerWidth - tooltipWidth - viewportGap,
  );
  const left = Math.min(Math.max(desiredLeft, viewportGap), maximumLeft);
  const estimatedHeight = 64;
  const fitsBelow =
    window.innerHeight - rect.bottom >=
    estimatedHeight + tooltipGap + viewportGap;
  const placement =
    fitsBelow || rect.top < estimatedHeight + tooltipGap + viewportGap
      ? "below"
      : "above";

  return {
    left,
    top:
      placement === "below" ? rect.bottom + tooltipGap : rect.top - tooltipGap,
    placement,
  };
}

function StructureGuideItem({
  item,
}: {
  item: (typeof structureLabels)[number];
}) {
  const triggerRef = useRef<HTMLSpanElement>(null);
  const [tooltipPosition, setTooltipPosition] =
    useState<StructureTooltipPosition | null>(null);
  const tooltipId = `structure-guide-tooltip-${item.value}`;
  const tooltipOpen = tooltipPosition !== null;

  const showTooltip = () => {
    if (triggerRef.current) {
      setTooltipPosition(getStructureTooltipPosition(triggerRef.current));
    }
  };

  useEffect(() => {
    if (!tooltipOpen) return;
    const repositionTooltip = () => {
      if (triggerRef.current) {
        setTooltipPosition(getStructureTooltipPosition(triggerRef.current));
      }
    };
    window.addEventListener("resize", repositionTooltip);
    window.addEventListener("scroll", repositionTooltip, true);
    return () => {
      window.removeEventListener("resize", repositionTooltip);
      window.removeEventListener("scroll", repositionTooltip, true);
    };
  }, [tooltipOpen]);

  return (
    <>
      <span
        ref={triggerRef}
        className="structure-guide-item"
        tabIndex={0}
        aria-describedby={tooltipOpen ? tooltipId : undefined}
        onMouseEnter={showTooltip}
        onMouseLeave={(event) => {
          if (document.activeElement !== event.currentTarget) {
            setTooltipPosition(null);
          }
        }}
        onFocus={showTooltip}
        onBlur={() => setTooltipPosition(null)}
      >
        <span className="typechip structure-chip" data-label={item.value}>
          {item.label}
        </span>
      </span>
      {tooltipPosition &&
        createPortal(
          <span
            id={tooltipId}
            className={`structure-tooltip-portal is-${tooltipPosition.placement}`}
            role="tooltip"
            style={{ left: tooltipPosition.left, top: tooltipPosition.top }}
          >
            {item.description}
          </span>,
          document.body,
        )}
    </>
  );
}

function StructureLabelMenu({
  id,
  value,
  disabled = false,
  showMeaning = false,
  ariaLabel = "Structure label",
  onChange,
}: {
  id?: string;
  value: ReviewType;
  disabled?: boolean;
  showMeaning?: boolean;
  ariaLabel?: string;
  onChange: (value: ReviewType) => void;
}) {
  const generatedId = useId();
  const menuId = `${id ?? generatedId}-menu`;
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedIndex = Math.max(
    0,
    structureLabels.findIndex((item) => item.value === value),
  );
  const selected = structureLabels[selectedIndex];

  useEffect(() => {
    if (!open) return;
    const focusFrame = window.requestAnimationFrame(() => {
      optionRefs.current[selectedIndex]?.focus();
    });
    const closeOnOutsidePress = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePress);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("pointerdown", closeOnOutsidePress);
    };
  }, [open, selectedIndex]);

  const moveFocus = (currentIndex: number, step: number) => {
    const next =
      (currentIndex + step + structureLabels.length) % structureLabels.length;
    optionRefs.current[next]?.focus();
  };

  return (
    <div
      className={`structure-label-select${open ? " is-open" : ""}${showMeaning ? " show-meaning" : ""}`}
      ref={rootRef}
    >
      <button
        id={id}
        className="structure-select-trigger"
        type="button"
        disabled={disabled}
        aria-label={`${ariaLabel}: ${selected.label}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className="structure-select-value">
          <span className="typechip structure-chip" data-label={selected.value}>
            {selected.label}
          </span>
          {showMeaning && (
            <span className="structure-select-meaning">
              {selected.shortMeaning}
            </span>
          )}
        </span>
        <ChevronDown aria-hidden="true" />
      </button>
      {open && (
        <div
          className="structure-select-menu"
          id={menuId}
          role="listbox"
          aria-label={ariaLabel}
        >
          {structureLabels.map((item, index) => (
            <button
              key={item.value}
              ref={(node) => {
                optionRefs.current[index] = node;
              }}
              type="button"
              role="option"
              aria-label={item.label}
              aria-selected={item.value === value}
              onClick={() => {
                onChange(item.value);
                setOpen(false);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  moveFocus(index, 1);
                } else if (event.key === "ArrowUp") {
                  event.preventDefault();
                  moveFocus(index, -1);
                } else if (event.key === "Home") {
                  event.preventDefault();
                  optionRefs.current[0]?.focus();
                } else if (event.key === "End") {
                  event.preventDefault();
                  optionRefs.current.at(-1)?.focus();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  setOpen(false);
                  (
                    document.getElementById(id ?? "") as HTMLElement | null
                  )?.focus();
                }
              }}
            >
              <span className="structure-select-option-copy">
                <span
                  className="typechip structure-chip"
                  data-label={item.value}
                >
                  {item.label}
                </span>
                {showMeaning && (
                  <span className="structure-option-meaning">
                    {item.shortMeaning}
                  </span>
                )}
              </span>
              {item.value === value && <Check aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const emptyTable: ReviewTableData = { headers: ["Column 1"], rows: [[""]] };

function cloneTable(table: ReviewTableData): ReviewTableData {
  return {
    caption: table.caption,
    headers: [...table.headers],
    rows: table.rows.map((row) => [...row]),
  };
}

function tableToText(table: ReviewTableData): string {
  return [table.headers, ...table.rows]
    .map((row) => row.join(" | "))
    .filter((row) => row.replaceAll("|", "").trim())
    .join("\n");
}

function tableToListText(table: ReviewTableData): string {
  const dataRows = table.rows
    .map((row) => row.map((cell) => cell.trim()).filter(Boolean))
    .filter((row) => row.length);

  const fallbackRows = dataRows.length
    ? dataRows
    : [
        table.headers
          .map((header) => header.trim())
          .filter((header) => header && !/^column \d+$/i.test(header)),
      ];

  return fallbackRows
    .filter((row) => row.length)
    .map((row) => {
      const [first, ...rest] = row;
      const marker = first?.match(/^\(?([0-9]+|[A-Za-z]|[ivxlcdm]+)[.)]?$/i);
      if (marker && rest.length) {
        const sourceMarker =
          first.includes("(") || /[.)]$/.test(first) ? first : `${first}.`;
        return `${sourceMarker} ${rest.join(" — ")}`;
      }
      return row.join(" — ");
    })
    .join("\n");
}

function isGenericHeader(value: string): boolean {
  return !value.trim() || /^column \d+$/i.test(value.trim());
}

function tableToStructuredText(
  table: ReviewTableData,
  targetType: ReviewType,
): string {
  if (targetType === "list") return tableToListText(table);

  const headers = table.headers.map((value) =>
    value.replaceAll("|", " ").replace(/\s+/g, " ").trim(),
  );
  const rows = table.rows
    .map((row) =>
      row.map((value) =>
        value.replaceAll("|", " ").replace(/\s+/g, " ").trim(),
      ),
    )
    .filter((row) => row.some(Boolean));
  const dataRows = rows.length
    ? rows
    : headers
        .filter((header) => header && !isGenericHeader(header))
        .map((header) => [header]);

  if (targetType === "form") {
    return dataRows
      .map((row) =>
        row
          .map((value, index) =>
            value
              ? !isGenericHeader(headers[index] ?? "")
                ? `${headers[index]}: ${value}`
                : value
              : "",
          )
          .filter(Boolean)
          .join("\n"),
      )
      .filter(Boolean)
      .join("\n\n");
  }

  if (targetType === "footnote") {
    return dataRows
      .map((row) => {
        const facts = row
          .map((value, index) =>
            value
              ? !isGenericHeader(headers[index] ?? "")
                ? `${headers[index]}: ${value}`
                : value
              : "",
          )
          .filter(Boolean);
        return facts.length ? `${facts.join("; ").replace(/\.$/, "")}.` : "";
      })
      .filter(Boolean)
      .join(" ");
  }

  return dataRows
    .map((row) => row.filter(Boolean).join(" — "))
    .filter(Boolean)
    .join("\n");
}

type ReviewListLine = {
  text: string;
  marker: string;
  ordered: boolean;
  value?: number;
};

function splitListItems(text: string): ReviewListLine[] {
  return text
    .split(/\r?\n/)
    .map((line) => {
      const value = line.trim();
      const ordered = value.match(
        /^(\(?(?:\d+|[A-Za-z]|[ivxlcdm]+)[.)])\s+(.+)$/i,
      );
      if (ordered) {
        const numericValue = ordered[1].match(/\d+/)?.[0];
        return {
          marker: ordered[1],
          text: ordered[2].trim(),
          ordered: true,
          value: numericValue ? Number(numericValue) : undefined,
        };
      }
      const bullet = value.match(/^([•\-–*])\s+(.+)$/);
      if (bullet)
        return { marker: bullet[1], text: bullet[2].trim(), ordered: false };
      return { marker: "", text: value, ordered: false };
    })
    .filter((item) => item.text);
}

function ReviewListPreview({ text }: { text: string }) {
  const items = splitListItems(text);
  const groups: ReviewListLine[][] = [];
  items.forEach((item) => {
    const group = groups.at(-1);
    if (!group || group[0].ordered !== item.ordered) groups.push([item]);
    else group.push(item);
  });

  return (
    <div className="review-list-preview">
      {groups.map((group, groupIndex) => {
        const children = group.map((item, index) => (
          <li
            value={item.ordered ? item.value : undefined}
            key={`${item.marker}-${item.text}-${index}`}
          >
            {item.text}
          </li>
        ));
        const firstNumber = group[0].marker.match(/\d+/)?.[0];
        return group[0].ordered ? (
          <ol
            start={firstNumber ? Number(firstNumber) : undefined}
            key={`ordered-${groupIndex}`}
          >
            {children}
          </ol>
        ) : (
          <ul key={`unordered-${groupIndex}`}>{children}</ul>
        );
      })}
    </div>
  );
}

function textToTable(text: string): ReviewTableData {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const rows = lines.map((line) =>
    line.includes("|") ? line.split("|").map((cell) => cell.trim()) : [line],
  );
  const width = Math.max(1, ...rows.map((row) => row.length));
  const normalised = rows.map((row) => [
    ...row,
    ...Array.from({ length: width - row.length }, () => ""),
  ]);
  if (normalised.length > 1)
    return { headers: normalised[0], rows: normalised.slice(1) };
  return {
    headers: Array.from({ length: width }, (_, index) => `Column ${index + 1}`),
    rows: normalised.length
      ? normalised
      : [Array.from({ length: width }, () => "")],
  };
}

const usesTableEditor = (type: ReviewType) =>
  type === "table" || type === "document_index";

const singleLineTypes: ReviewType[] = [
  "title",
  "caption",
  "section_header_1",
  "section_header_2",
  "section_header_3",
  "section_header_4",
  "section_header_5",
];

function evidenceVersion(item: ReviewItem): string {
  const bounds = item.source.bounds;
  return [
    item.blockId ?? item.id,
    item.source.page,
    bounds?.left,
    bounds?.top,
    bounds?.right,
    bounds?.bottom,
  ]
    .filter((value) => value !== undefined)
    .join(":");
}

/** Headings, titles and captions are one line: strip bullets and join lines. */
function toSingleLine(text: string): string {
  return text
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(/^\s*(?:[•\-–*]|\d+[.)])\s*/, "")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .filter(Boolean)
    .join(" ");
}

function TableExtract({
  table,
  caption,
}: {
  table?: ReviewTableData;
  caption?: string;
}) {
  if (!table)
    return <div className="extract-box">No table cells were extracted.</div>;

  return (
    <div
      className="extract-box review-table-scroll"
      tabIndex={0}
      role="region"
      aria-label={`${caption?.trim() || "Table"}; scroll horizontally when needed`}
    >
      <table className="review-table-extract">
        {caption?.trim() ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {table.headers.map((header, index) => (
              <th scope="col" key={`${header}-${index}`}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {table.headers.map((_, columnIndex) => (
                <td key={`cell-${rowIndex}-${columnIndex}`}>
                  {row[columnIndex] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TableEditor({
  table,
  onChange,
}: {
  table: ReviewTableData;
  onChange: (table: ReviewTableData) => void;
}) {
  const updateHeader = (columnIndex: number, value: string) => {
    const next = cloneTable(table);
    next.headers[columnIndex] = value;
    onChange(next);
  };

  const updateCell = (rowIndex: number, columnIndex: number, value: string) => {
    const next = cloneTable(table);
    next.rows[rowIndex] = next.headers.map(
      (_, index) => next.rows[rowIndex]?.[index] ?? "",
    );
    next.rows[rowIndex][columnIndex] = value;
    onChange(next);
  };

  const addColumn = () => {
    onChange({
      ...table,
      headers: [...table.headers, `Column ${table.headers.length + 1}`],
      rows: table.rows.map((row) => [...row, ""]),
    });
  };

  const removeColumn = (columnIndex: number) => {
    if (table.headers.length === 1) return;
    onChange({
      ...table,
      headers: table.headers.filter((_, index) => index !== columnIndex),
      rows: table.rows.map((row) =>
        row.filter((_, index) => index !== columnIndex),
      ),
    });
  };

  const addRow = () =>
    onChange({ ...table, rows: [...table.rows, table.headers.map(() => "")] });
  const removeRow = (rowIndex: number) =>
    onChange({
      ...table,
      rows: table.rows.filter((_, index) => index !== rowIndex),
    });

  return (
    <div className="review-table-editor">
      <label className="review-table-caption-field">
        Table caption (optional)
        <input
          className="input"
          value={table.caption ?? ""}
          onChange={(event) =>
            onChange({ ...table, caption: event.target.value })
          }
          placeholder="Use the caption from the original document"
        />
      </label>
      <div className="review-table-editor-head">
        <span>
          Edit each header or cell directly. Rows and columns can also be added
          or removed.
        </span>
        <button
          className="btn btn-outline btn-sm"
          type="button"
          onClick={addColumn}
        >
          <Plus />
          Add column
        </button>
      </div>
      <div
        className="review-table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Editable corrected table; scroll horizontally when needed"
      >
        <table className="review-table-extract editable-review-table">
          <caption className="sr-only">Editable corrected table</caption>
          <thead>
            <tr>
              {table.headers.map((header, columnIndex) => (
                <th scope="col" key={`header-${columnIndex}`}>
                  <div className="editable-table-header">
                    <input
                      className="input"
                      aria-label={`Header ${columnIndex + 1}`}
                      value={header}
                      onChange={(event) =>
                        updateHeader(columnIndex, event.target.value)
                      }
                    />
                    <button
                      className="btn btn-ghost btn-sm icon-button"
                      type="button"
                      disabled={table.headers.length === 1}
                      aria-label={`Remove column ${header || columnIndex + 1}`}
                      onClick={() => removeColumn(columnIndex)}
                    >
                      <Trash2 />
                    </button>
                  </div>
                </th>
              ))}
              <th scope="col" className="table-row-actions">
                Row actions
              </th>
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
                      value={row[columnIndex] ?? ""}
                      onChange={(event) =>
                        updateCell(rowIndex, columnIndex, event.target.value)
                      }
                    />
                  </td>
                ))}
                <td className="table-row-actions">
                  <button
                    className="btn btn-ghost btn-sm icon-button"
                    type="button"
                    aria-label={`Remove row ${rowIndex + 1}`}
                    onClick={() => removeRow(rowIndex)}
                  >
                    <Trash2 />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button className="btn btn-outline btn-sm" type="button" onClick={addRow}>
        <Plus />
        Add row
      </button>
    </div>
  );
}

function ListEditor({
  text,
  onChange,
}: {
  text: string;
  onChange: (text: string) => void;
}) {
  const editableItems = text
    ? text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
    : [""];
  const update = (next: string[]) => onChange(next.join("\n"));

  return (
    <div
      className="review-list-editor"
      role="group"
      aria-label="Editable corrected list"
    >
      <div className="review-list-editor-head">
        <span>
          Each row becomes one semantic list item. Keep markers such as 1., 2.
          for an ordered list; use a bullet marker or no number for an unordered
          list.
        </span>
        <button
          className="btn btn-outline btn-sm"
          type="button"
          onClick={() => update([...editableItems, ""])}
        >
          <Plus />
          Add item
        </button>
      </div>
      <div className="review-list-editor-items">
        {editableItems.map((item, index) => (
          <div className="review-list-editor-item" key={`list-item-${index}`}>
            <span aria-hidden="true">Item {index + 1}</span>
            <textarea
              className="input"
              rows={2}
              aria-label={`List item ${index + 1}`}
              value={item}
              onChange={(event) => {
                const next = [...editableItems];
                next[index] = event.target.value;
                update(next);
              }}
            />
            <button
              className="btn btn-ghost btn-sm icon-button"
              type="button"
              aria-label={`Remove list item ${index + 1}`}
              disabled={editableItems.length === 1}
              onClick={() =>
                update(
                  editableItems.filter((_, itemIndex) => itemIndex !== index),
                )
              }
            >
              <Trash2 />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReviewPage() {
  const navigate = useNavigate();
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
    bulkUpdateReviewItems,
    unlock,
    showToast,
  } = useKonverter();
  const processingSummaryQuery = useQuery({
    queryKey: ["processing-summary", activeDocumentId ?? "none"],
    queryFn: () => documentService.getProcessingSummary(activeDocumentId!),
    enabled: Boolean(activeDocumentId),
  });
  const processingSummary = processingSummaryQuery.data;
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [labelFilter, setLabelFilter] = useState<LabelFilter>("all");
  const [sort, setSort] = useState<Sort>("highest");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [bulkSelectedIds, setBulkSelectedIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [bulkAction, setBulkAction] = useState<BulkAction>("accept");
  const [bulkType, setBulkType] = useState<ReviewType>("text");
  const [pendingConfirmation, setPendingConfirmation] =
    useState<PendingConfirmation | null>(null);
  const [confirmationApplying, setConfirmationApplying] = useState(false);
  const [processingDetailsOpen, setProcessingDetailsOpen] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const [editType, setEditType] = useState<ReviewType>("text");
  const [editTable, setEditTable] = useState<ReviewTableData>(emptyTable);
  const [uploadedPicture, setUploadedPicture] = useState<string | null>(null);
  const [showDetailMobile, setShowDetailMobile] = useState(false);
  const [evidenceFailed, setEvidenceFailed] = useState(false);
  const [evidenceLoading, setEvidenceLoading] = useState(true);
  const previousFilteredIds = useRef<string[]>([]);
  const queueListRef = useRef<HTMLDivElement | null>(null);
  const selectionAnchorRef = useRef("");
  const tabModifierHeldRef = useRef(false);

  useEffect(() => {
    unlock("metadata");
  }, [unlock]);

  const completedDocumentIds = completedDocuments
    .map((document) => document.id)
    .join("|");

  useEffect(() => {
    if (
      completedDocuments.length &&
      !completedDocuments.some((document) => document.id === activeDocumentId)
    ) {
      selectDocument(completedDocuments[0].id);
    }
  }, [activeDocumentId, completedDocumentIds, selectDocument]);

  const filteredItems = useMemo(() => {
    let list = [...reviewItems];
    if (statusFilter !== "all")
      list = list.filter((item) => item.status === statusFilter);
    if (labelFilter !== "all")
      list = list.filter((item) => item.type === labelFilter);
    const normalisedQuery = query.trim().toLowerCase();
    if (normalisedQuery) {
      list = list.filter((item) =>
        [
          item.title,
          item.label,
          item.extractedText,
          item.correctedText,
          item.note,
          ...(item.keyValues?.flat() ?? []),
          ...(item.tableData
            ? [item.tableData.headers, ...item.tableData.rows].flat()
            : []),
          ...(item.correctedTable
            ? [item.correctedTable.headers, ...item.correctedTable.rows].flat()
            : []),
        ]
          .filter(Boolean)
          .some((value) =>
            String(value).toLowerCase().includes(normalisedQuery),
          ),
      );
    }
    list.sort(
      sort === "highest"
        ? (a, b) => b.confidence - a.confidence
        : sort === "lowest"
          ? (a, b) => a.confidence - b.confidence
          : (a, b) => a.page - b.page,
    );
    return list;
  }, [labelFilter, query, reviewItems, sort, statusFilter]);

  const selected = filteredItems.find((item) => item.id === selectedId);
  const selectedPosition = selected
    ? filteredItems.findIndex((item) => item.id === selected.id) + 1
    : 0;

  useLayoutEffect(() => {
    const nextIds = filteredItems.map((item) => item.id);
    if (!nextIds.length) {
      if (selectedId) setSelectedId("");
      previousFilteredIds.current = [];
      return;
    }
    if (selectedId && nextIds.includes(selectedId)) {
      previousFilteredIds.current = nextIds;
      return;
    }

    const previous = previousFilteredIds.current;
    const previousIndex = previous.indexOf(selectedId);
    let nextId = "";
    if (previousIndex >= 0) {
      for (let index = previousIndex + 1; index < previous.length; index += 1) {
        if (nextIds.includes(previous[index])) {
          nextId = previous[index];
          break;
        }
      }
      if (!nextId) {
        for (let index = previousIndex - 1; index >= 0; index -= 1) {
          if (nextIds.includes(previous[index])) {
            nextId = previous[index];
            break;
          }
        }
      }
    }
    setSelectedId(nextId || nextIds[0]);
    previousFilteredIds.current = nextIds;
  }, [filteredItems, selectedId]);

  useEffect(() => {
    const visibleIds = new Set(filteredItems.map((item) => item.id));
    setBulkSelectedIds((current) => {
      const next = new Set([...current].filter((id) => visibleIds.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [filteredItems]);

  const allVisibleSelected =
    filteredItems.length > 0 &&
    filteredItems.every((item) => bulkSelectedIds.has(item.id));

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      if (event.key === "Tab") tabModifierHeldRef.current = true;
    };
    const keyUp = (event: KeyboardEvent) => {
      if (event.key === "Tab") tabModifierHeldRef.current = false;
    };
    const clearModifier = () => {
      tabModifierHeldRef.current = false;
    };
    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    window.addEventListener("blur", clearModifier);
    return () => {
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
      window.removeEventListener("blur", clearModifier);
    };
  }, []);

  useEffect(() => {
    setEvidenceFailed(false);
    setEvidenceLoading(true);
  }, [activeDocumentId, selected?.id]);

  const preserveQueueScroll = () => {
    const scrollTop = queueListRef.current?.scrollTop ?? 0;
    window.requestAnimationFrame(() => {
      if (queueListRef.current) queueListRef.current.scrollTop = scrollTop;
    });
  };

  const act = async (item: ReviewItem, status: "accepted" | "removed") => {
    await setReviewStatus(item.id, status);
    preserveQueueScroll();
    showToast(
      status === "accepted"
        ? "Item accepted"
        : "Item removed from generated output",
    );
    setEditing(false);
  };

  const beginEdit = (item: ReviewItem) => {
    setEditing(true);
    const table = cloneTable(
      item.correctedTable ?? item.tableData ?? emptyTable,
    );
    setEditText(item.correctedText ?? item.extractedText ?? tableToText(table));
    setEditType(item.type);
    setEditTable(table);
  };

  const saveEdit = async (item: ReviewItem) => {
    const label =
      structureLabels.find((entry) => entry.value === editType)?.label ??
      editType;
    await saveReviewItem(item.id, {
      type: editType,
      label,
      status: "edited",
      ...(editType === "box_section"
        ? {}
        : usesTableEditor(editType)
          ? { correctedTable: editTable }
          : { correctedText: editText }),
    });
    preserveQueueScroll();
    setEditing(false);
    showToast("Review changes saved");
  };

  const changeEditType = (nextType: ReviewType) => {
    if (usesTableEditor(nextType) && !usesTableEditor(editType)) {
      setEditTable(textToTable(editText));
    } else if (!usesTableEditor(nextType) && usesTableEditor(editType)) {
      const converted = tableToStructuredText(editTable, nextType);
      setEditText(
        singleLineTypes.includes(nextType)
          ? toSingleLine(converted)
          : converted,
      );
    } else if (
      singleLineTypes.includes(nextType) &&
      !singleLineTypes.includes(editType)
    ) {
      // e.g. a list converted into a heading collapses to one clean line.
      setEditText((current) => toSingleLine(current));
    }
    setEditType(nextType);
  };

  const restoreToOutput = async (item: ReviewItem) => {
    await setReviewStatus(item.id, "accepted");
    preserveQueueScroll();
    showToast("Item restored to generated output");
  };

  const toggleBulkItem = (id: string) => {
    setBulkSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllVisible = () => {
    setBulkSelectedIds((current) => {
      const next = new Set(current);
      if (allVisibleSelected)
        filteredItems.forEach((item) => next.delete(item.id));
      else filteredItems.forEach((item) => next.add(item.id));
      return next;
    });
    selectionAnchorRef.current = filteredItems.at(-1)?.id ?? "";
  };

  const openReviewItem = (item: ReviewItem) => {
    setSelectedId(item.id);
    setEditing(false);
    setUploadedPicture(null);
    setEvidenceFailed(false);
    setEvidenceLoading(true);
    setShowDetailMobile(true);
  };

  const handleQueueItemClick = (
    event: ReactMouseEvent<HTMLButtonElement>,
    item: ReviewItem,
  ) => {
    const shiftClick = event.shiftKey;
    const anchorId = selectionAnchorRef.current;
    const additiveClick =
      shiftClick ||
      event.ctrlKey ||
      event.metaKey ||
      tabModifierHeldRef.current;
    if (additiveClick) {
      event.preventDefault();
      setBulkSelectedIds((current) => {
        const next = new Set(current);
        if (shiftClick && anchorId) {
          const anchorIndex = filteredItems.findIndex(
            (entry) => entry.id === anchorId,
          );
          const itemIndex = filteredItems.findIndex(
            (entry) => entry.id === item.id,
          );
          if (anchorIndex >= 0 && itemIndex >= 0) {
            const [start, end] = [anchorIndex, itemIndex].sort((a, b) => a - b);
            filteredItems
              .slice(start, end + 1)
              .forEach((entry) => next.add(entry.id));
          } else next.add(item.id);
        } else if (next.has(item.id)) next.delete(item.id);
        else next.add(item.id);
        return next;
      });
    }
    selectionAnchorRef.current = item.id;
    openReviewItem(item);
  };

  const requestBulkAction = () => {
    const ids = [...bulkSelectedIds];
    if (!ids.length) return;
    const selectedLabel =
      structureLabels.find((entry) => entry.value === bulkType)?.label ??
      bulkType;
    const message =
      bulkAction === "accept"
        ? `Accept ${ids.length} selected item${ids.length === 1 ? "" : "s"}?`
        : bulkAction === "remove"
          ? `Remove ${ids.length} selected item${ids.length === 1 ? "" : "s"} from the final output?`
          : `Change ${ids.length} selected item${ids.length === 1 ? "" : "s"} to ${selectedLabel}?`;
    setPendingConfirmation({
      kind: "bulk",
      ids,
      action: bulkAction,
      selectedType: bulkType,
      selectedLabel,
      message,
    });
  };

  const applyConfirmedBulkAction = async (
    confirmation: Extract<PendingConfirmation, { kind: "bulk" }>,
  ) => {
    const { ids, action, selectedLabel, selectedType } = confirmation;
    await bulkUpdateReviewItems(
      ids,
      action === "accept"
        ? { status: "accepted" }
        : action === "remove"
          ? { status: "removed" }
          : { type: selectedType, label: selectedLabel, status: "edited" },
    );
    preserveQueueScroll();
    showToast(
      action === "accept"
        ? `${ids.length} item${ids.length === 1 ? "" : "s"} accepted`
        : action === "remove"
          ? `${ids.length} item${ids.length === 1 ? "" : "s"} removed from output`
          : `${ids.length} item${ids.length === 1 ? "" : "s"} changed to ${selectedLabel}`,
    );
  };

  const performDocumentSwitch = (nextId: string) => {
    if (nextId === activeDocumentId) return;
    const nextDocument = completedDocuments.find(
      (document) => document.id === nextId,
    );
    setEditing(false);
    setSelectedId("");
    setShowDetailMobile(false);
    setEvidenceFailed(false);
    setEvidenceLoading(true);
    selectDocument(nextId);
    showToast(
      `Now reviewing ${nextDocument?.fileName ?? "the selected document"}`,
    );
  };

  const switchReviewDocument = (nextId: string) => {
    if (nextId === activeDocumentId) return;
    if (editing) {
      setPendingConfirmation({
        kind: "switch-document",
        nextId,
        message:
          "Switch documents and discard the unsaved changes in this review item?",
      });
      return;
    }
    performDocumentSwitch(nextId);
  };

  const confirmPendingAction = async () => {
    const confirmation = pendingConfirmation;
    if (!confirmation) return;
    if (confirmation.kind === "switch-document") {
      setPendingConfirmation(null);
      performDocumentSwitch(confirmation.nextId);
      return;
    }
    setConfirmationApplying(true);
    try {
      await applyConfirmedBulkAction(confirmation);
      setPendingConfirmation(null);
    } catch {
      showToast("The bulk change could not be applied. Please try again.");
    } finally {
      setConfirmationApplying(false);
    }
  };

  const uploadPicture = async (item: ReviewItem, file?: File) => {
    if (!file) return;
    setUploadedPicture(file.name);
    await setReviewStatus(item.id, "edited");
    showToast("Replacement picture uploaded");
  };

  const continueToMetadata = () => {
    unlock("metadata");
    navigate(converterStagePath("metadata"));
  };

  return (
    <section className="screen active" aria-labelledby="review-heading">
      <div className="section-title review-titlebar">
        <div>
          <span className="eyebrow">Stage 2 of 4</span>
          <h2 id="review-heading">Review</h2>
          <p className="lead">
            Focus on the items that need a human decision and with low
            confidence scores.
          </p>
        </div>
        <div className="review-title-actions">
          <details className="review-guidance review-guidance-popover">
            <summary className="btn btn-outline btn-sm">
              <CircleHelp aria-hidden="true" />
              Review guidance
            </summary>
            <div
              className="review-guidance-body"
              role="region"
              aria-label="Review guidance"
            >
              <div>
                <h3>What the confidence score means</h3>
                <p>
                  The percentage is the layout model’s certainty about the{" "}
                  <b>structure label</b>—for example H2, Table or Picture—not
                  the wording itself. Low-confidence labels are the most likely
                  to need correction.
                </p>
                <h3>How to resolve a flag</h3>
                <ol>
                  <li>
                    Compare the extracted result with the original PDF evidence.
                  </li>
                  <li>
                    Select <b>Accept</b> when the result is correct.
                  </li>
                  <li>
                    Select <b>Edit</b> to change the text, table cells, or
                    structure label.
                  </li>
                  <li>
                    Use <b>Remove from output</b> for duplicates, decoration, or
                    extraction artefacts.
                  </li>
                </ol>
              </div>
              <div>
                <h3>Structure label guide</h3>
                <div
                  className="structure-guide"
                  aria-label="Structure label definitions"
                >
                  {structureLabels.map((item) => (
                    <StructureGuideItem key={item.value} item={item} />
                  ))}
                </div>
              </div>
            </div>
          </details>
          <div className="review-next-step">
            <span>
              {pendingCount
                ? "Clear required items to continue"
                : "Required review complete"}
            </span>
            <button
              className="btn btn-primary btn-sm"
              disabled={pendingCount > 0}
              onClick={continueToMetadata}
            >
              Continue to metadata →
            </button>
          </div>
        </div>
      </div>

      {(completedDocuments.length > 1 || runningDocuments.length > 0) && (
        <section
          className="review-document-switcher"
          aria-labelledby="review-document-heading"
        >
          <div>
            <span className="eyebrow">Ready documents</span>
            <h3 id="review-document-heading">
              Choose which document to review
            </h3>
            <p>
              {completedDocuments.length} completed
              {runningDocuments.length
                ? ` · ${runningDocuments.length} still processing in the background`
                : ""}
            </p>
            <span
              className="active-review-document"
              role="status"
              aria-live="polite"
            >
              Currently reviewing:{" "}
              <strong>
                {activeDocument?.fileName ?? completedDocuments[0].fileName}
              </strong>
            </span>
          </div>
          <label htmlFor="review-document-select">
            Document
            <select
              id="review-document-select"
              className="sel"
              value={
                completedDocuments.some(
                  (document) => document.id === activeDocumentId,
                )
                  ? (activeDocumentId ?? "")
                  : completedDocuments[0].id
              }
              onChange={(event) => switchReviewDocument(event.target.value)}
            >
              {completedDocuments.map((document) => (
                <option key={document.id} value={document.id}>
                  {document.fileName}
                </option>
              ))}
            </select>
          </label>
          {runningDocuments.length > 0 && (
            <button
              className="btn btn-outline btn-sm"
              onClick={() => navigate(converterStagePath("upload"))}
            >
              View processing queue
            </button>
          )}
        </section>
      )}

      <details
        className="processing-details-section"
        open={processingDetailsOpen}
        onToggle={(event) => setProcessingDetailsOpen(event.currentTarget.open)}
      >
        <summary>
          <span className="processing-details-title">
            <FileText aria-hidden="true" />
            <span>
              <strong>Processing details</strong>
              <small>Document elements detected during conversion</small>
            </span>
          </span>
          <ChevronDown
            className="processing-details-chevron"
            aria-hidden="true"
          />
        </summary>
        <div className="processing-details-body">
          {processingSummary ? (
            <section
              className="element-summary"
              aria-labelledby="element-summary-heading"
            >
              <div>
                <span className="eyebrow">Extraction coverage</span>
                <h3 id="element-summary-heading">Document elements detected</h3>
              </div>
              {(
                [
                  ["Pages", processingSummary.pages],
                  ["Headings", processingSummary.headings],
                  ["Images", processingSummary.images],
                  ["Tables", processingSummary.tables],
                ] as const
              ).map(([label, coverage]) => (
                <div
                  className={`element-stat${coverage.needsReview ? " has-issue" : ""}`}
                  key={label}
                >
                  <strong className="mono">
                    {coverage.detected} / {coverage.total}
                  </strong>
                  <span>{label}</span>
                  {coverage.needsReview > 0 && (
                    <small>
                      {coverage.needsReview}{" "}
                      {coverage.needsReview === 1 ? "needs" : "need"} review
                    </small>
                  )}
                </div>
              ))}
            </section>
          ) : (
            <div className="processing-details-loading" role="status">
              {processingSummaryQuery.isError
                ? "Extraction coverage is temporarily unavailable."
                : "Loading extraction coverage…"}
            </div>
          )}
        </div>
      </details>

      <div className="toolbar review-toolbar">
        <div className="tb-control search-control">
          <label htmlFor="review-search">Search queue</label>
          <span className="search-input-wrap">
            <Search aria-hidden="true" />
            <input
              id="review-search"
              className="input"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search labels and extracted text"
            />
          </span>
        </div>
        <details className="review-filter-disclosure">
          <summary className="btn btn-outline btn-sm">Filters</summary>
          <div className="review-filter-controls">
            <div className="tb-control">
              <label htmlFor="show-filter">Status</label>
              <span className="review-filter-select">
                <select
                  id="show-filter"
                  className="sel"
                  value={statusFilter}
                  onChange={(event) => {
                    setStatusFilter(event.target.value as StatusFilter);
                    setShowDetailMobile(false);
                  }}
                >
                  <option value="all">All items</option>
                  <option value="pending">Pending</option>
                  <option value="accepted">Accepted</option>
                  <option value="edited">Edited</option>
                  <option value="removed">Removed from output</option>
                </select>
                <ChevronDown aria-hidden="true" />
              </span>
            </div>
            <div className="tb-control">
              <label htmlFor="label-filter">Filter by structure label</label>
              <span className="review-filter-select">
                <select
                  id="label-filter"
                  className="sel"
                  aria-label="Filter by structure label"
                  value={labelFilter}
                  onChange={(event) => {
                    setLabelFilter(event.target.value as LabelFilter);
                    setShowDetailMobile(false);
                  }}
                >
                  <option value="all">All labels</option>
                  {structureLabels.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                <ChevronDown aria-hidden="true" />
              </span>
            </div>
            <div className="tb-control">
              <label htmlFor="sort-filter">Sort</label>
              <span className="review-filter-select">
                <select
                  id="sort-filter"
                  className="sel"
                  value={sort}
                  onChange={(event) => setSort(event.target.value as Sort)}
                >
                  <option value="highest">Highest confidence</option>
                  <option value="lowest">Lowest confidence</option>
                  <option value="page">Page order</option>
                </select>
                <ChevronDown aria-hidden="true" />
              </span>
            </div>
          </div>
        </details>
      </div>

      <p className="mobile-hint">Tap a flagged item to review it.</p>
      <div className={`review-grid ${showDetailMobile ? "show-detail" : ""}`}>
        <div className="queue">
          <div className="queue-head">
            <h3 className="queue-title">Review queue</h3>
            <span className="queue-count">
              {filteredItems.length} item{filteredItems.length === 1 ? "" : "s"}
            </span>
          </div>
          <div
            className={`queue-selection-row${bulkSelectedIds.size ? " has-selection" : ""}`}
          >
            <button
              className="btn btn-ghost btn-sm queue-select-all"
              type="button"
              disabled={!filteredItems.length}
              aria-pressed={allVisibleSelected}
              onClick={toggleAllVisible}
            >
              <Check aria-hidden="true" />
              {allVisibleSelected
                ? "Clear visible selection"
                : "Select all visible"}
            </button>
            <span className="queue-count" role="status" aria-live="polite">
              {bulkSelectedIds.size
                ? `${bulkSelectedIds.size} selected`
                : "Shift+click or Tab+click"}
            </span>
          </div>
          {bulkSelectedIds.size > 0 && (
            <div
              className="queue-bulk-action-panel"
              aria-label="Bulk review actions"
            >
              <label>
                Action
                <select
                  className="sel"
                  aria-label="Bulk action"
                  value={bulkAction}
                  onChange={(event) =>
                    setBulkAction(event.target.value as BulkAction)
                  }
                >
                  <option value="accept">Accept selected</option>
                  <option value="remove">Remove from output</option>
                  <option value="label">Change structure label</option>
                </select>
              </label>
              {bulkAction === "label" && (
                <div className="bulk-structure-field">
                  <span>Structure label</span>
                  <StructureLabelMenu
                    id="bulk-structure-label"
                    ariaLabel="Bulk structure label"
                    value={bulkType}
                    onChange={setBulkType}
                  />
                </div>
              )}
              <button
                className="btn btn-primary btn-sm"
                type="button"
                onClick={requestBulkAction}
              >
                Apply to {bulkSelectedIds.size} selected
              </button>
            </div>
          )}
          <div
            className="qlist"
            role="list"
            aria-label="Flagged items"
            ref={queueListRef}
          >
            {reviewLoading && (
              <div style={{ padding: 20 }}>Loading review items…</div>
            )}
            {!reviewLoading && filteredItems.length === 0 && (
              <div className="empty-filter">No items match these filters.</div>
            )}
            {filteredItems.map((item) => (
              <div
                className={`qitem-row tone-${itemTone(item)}${selected?.id === item.id ? " is-current" : ""}`}
                role="listitem"
                key={item.id}
              >
                <label className="batch-select">
                  {bulkSelectedIds.size > 0 && (
                    <input
                      type="checkbox"
                      checked={bulkSelectedIds.has(item.id)}
                      onChange={() => toggleBulkItem(item.id)}
                      aria-label={`Select ${item.title} for a bulk action`}
                    />
                  )}
                </label>
                <button
                  className={`qitem tone-${itemTone(item)}`}
                  aria-current={selected?.id === item.id ? "true" : undefined}
                  aria-pressed={
                    bulkSelectedIds.size
                      ? bulkSelectedIds.has(item.id)
                      : undefined
                  }
                  onClick={(event) => handleQueueItemClick(event, item)}
                >
                  <div className="qitem-top">
                    <StructureChip item={item} />
                    <ConfidenceBadge band={item.band} score={item.confidence} />
                    <span className="pg">p.{item.page}</span>
                  </div>
                  <div className="qitem-txt">{item.title}</div>
                  <div className="qitem-bot">
                    <StatusTag status={item.status} />
                  </div>
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="detail">
          {selected ? (
            <>
              <button
                className="mobile-back"
                type="button"
                onClick={() => setShowDetailMobile(false)}
              >
                ← Back to flagged queue
              </button>
              <div className="detail-head">
                <StructureChip item={selected} />
                <ConfidenceBadge
                  band={selected.band}
                  score={selected.confidence}
                />
                <StatusTag status={selected.status} />
                <span className="mono detail-page">
                  Flag {selectedPosition} of {filteredItems.length} · page{" "}
                  {selected.page}
                </span>
              </div>
              <div className="detail-body">
                <h3 className="detail-title">{selected.title}</h3>
                {selected.note && (
                  <div className="callout">
                    <FileText />
                    {selected.note}
                  </div>
                )}

                <div className="field-label source-label">
                  Where this came from
                </div>
                <div className="detail-source review-evidence-card">
                  <div className="detail-source-head">
                    <FileText />
                    Original PDF evidence
                    <a
                      className="source-page-link"
                      href={publicationService.sourceUrl(
                        activeDocumentId ?? "",
                        selected.source.page,
                      )}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open original page <ExternalLink aria-hidden="true" />
                    </a>
                    <span className="mono">p.{selected.source.page}</span>
                  </div>
                  <div
                    className={`page-doc source-evidence-preview${evidenceLoading && !evidenceFailed ? " is-loading" : ""}`}
                  >
                    {!evidenceFailed ? (
                      <>
                        {evidenceLoading && (
                          <div
                            className="source-evidence-loading"
                            role="status"
                          >
                            <LoaderCircle
                              className="spinner-icon"
                              aria-hidden="true"
                            />
                            Loading the matching source crop…
                          </div>
                        )}
                        <img
                          key={`${activeDocumentId}-${selected.id}-${evidenceVersion(selected)}`}
                          className={evidenceLoading ? "is-loading" : undefined}
                          src={publicationService.evidenceUrl(
                            activeDocumentId ?? "",
                            selected.id,
                            evidenceVersion(selected),
                          )}
                          alt={`Original PDF evidence for ${selected.label} on page ${selected.source.page}`}
                          loading="eager"
                          onLoad={() => setEvidenceLoading(false)}
                          onError={() => {
                            setEvidenceLoading(false);
                            setEvidenceFailed(true);
                          }}
                        />
                      </>
                    ) : (
                      <div className="source-evidence-fallback">
                        <TriangleAlert aria-hidden="true" />
                        <span>
                          The visual crop is unavailable. Open the original page
                          to compare the source directly.
                        </span>
                      </div>
                    )}
                  </div>
                  {!selected.source.bounds && !evidenceFailed && (
                    <p className="source-evidence-note">
                      Precise coordinates were unavailable, so the complete
                      source page is shown.
                    </p>
                  )}
                </div>

                <div className="structure-label-editor">
                  <div className="structure-label-copy">
                    <label htmlFor="selected-structure-label">
                      Structure label
                    </label>
                    <small>
                      Choose the label that best describes this content.
                    </small>
                  </div>
                  <StructureLabelMenu
                    id="selected-structure-label"
                    value={editing ? editType : selected.type}
                    disabled={!editing}
                    showMeaning
                    onChange={changeEditType}
                  />
                </div>

                <div className="field-label">
                  Extracted result (reference only)
                </div>
                {selected.kind === "kv" ? (
                  <dl className="kv extract-box">
                    {selected.keyValues?.map(([key, value]) => (
                      <div key={key} style={{ display: "contents" }}>
                        <dt>{key}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : selected.kind === "table" ? (
                  <TableExtract
                    table={selected.tableData}
                    caption={selected.tableData?.caption}
                  />
                ) : (
                  <div className="extract-box pre-wrap">
                    {selected.extractedText || (
                      <span style={{ color: "var(--muted)" }}>
                        No text or image was extracted.
                      </span>
                    )}
                  </div>
                )}

                {selected.correctedTable && !editing && (
                  <>
                    <div className="field-label">Saved corrected table</div>
                    <TableExtract
                      table={selected.correctedTable}
                      caption={selected.correctedTable.caption}
                    />
                  </>
                )}

                {selected.correctedText &&
                  !editing &&
                  selected.type !== "box_section" && (
                    <>
                      <div className="field-label">Saved correction</div>
                      {selected.type === "list" ? (
                        <ReviewListPreview text={selected.correctedText} />
                      ) : (
                        <div className="corrected-result pre-wrap">
                          {selected.correctedText}
                        </div>
                      )}
                    </>
                  )}

                {editing && (
                  <div className="correction-editor">
                    <div className="field-label">
                      {usesTableEditor(editType)
                        ? "Corrected table"
                        : editType === "box_section"
                          ? "Box Section structure"
                          : "Corrected result"}
                    </div>
                    {usesTableEditor(editType) ? (
                      <TableEditor table={editTable} onChange={setEditTable} />
                    ) : editType === "list" ? (
                      <ListEditor text={editText} onChange={setEditText} />
                    ) : editType === "box_section" ? (
                      <div className="box-section-edit-note">
                        Child paragraphs, lists, tables, figures and footnotes
                        stay as separate semantic elements. Change the container
                        label here; its child content is not flattened into one
                        text field.
                      </div>
                    ) : (
                      <textarea
                        className="extract-input"
                        aria-label="Corrected text"
                        rows={4}
                        value={editText}
                        onChange={(event) => setEditText(event.target.value)}
                        autoFocus
                      />
                    )}
                    <div className="hint">
                      {usesTableEditor(editType)
                        ? "This structure is corrected as rows and columns."
                        : editType === "list"
                          ? "Enter one list item per line."
                          : editType === "box_section"
                            ? "The Box Section remains a container in every generated output."
                            : "This structure is corrected as text."}
                    </div>
                  </div>
                )}

                {selected.type === "picture" && (
                  <div className="manual-picture-upload">
                    <div>
                      <strong>
                        {uploadedPicture
                          ? "Replacement picture ready"
                          : "Picture extraction failed"}
                      </strong>
                      <span>
                        {uploadedPicture ??
                          "Upload the picture manually if it is missing from the extracted result."}
                      </span>
                    </div>
                    <label
                      className="btn btn-outline btn-sm"
                      aria-disabled={!editing}
                    >
                      <ImageUp />
                      Upload picture
                      <input
                        className="sr-only"
                        type="file"
                        accept="image/*"
                        disabled={!editing}
                        onChange={(event) =>
                          void uploadPicture(selected, event.target.files?.[0])
                        }
                      />
                    </label>
                  </div>
                )}
              </div>
              <div className="actionbar detail-actions">
                {editing ? (
                  <>
                    <button
                      className="btn btn-primary review-save-action"
                      onClick={() => saveEdit(selected)}
                    >
                      <Check />
                      Save changes
                    </button>
                    <button
                      className="btn btn-outline"
                      onClick={() => setEditing(false)}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      className="btn btn-outline"
                      disabled={selected.status === "accepted"}
                      onClick={() => act(selected, "accepted")}
                    >
                      <Check />
                      Accept
                    </button>
                    <button
                      className="btn btn-outline"
                      aria-label="Edit flagged item"
                      onClick={() => beginEdit(selected)}
                    >
                      <Pencil />
                      Edit
                    </button>
                    {selected.status === "removed" ? (
                      <button
                        className="btn btn-outline"
                        onClick={() => restoreToOutput(selected)}
                      >
                        <RotateCcw />
                        Restore to output
                      </button>
                    ) : (
                      <button
                        className="btn btn-danger"
                        onClick={() => act(selected, "removed")}
                      >
                        <Trash2 />
                        Remove from output
                      </button>
                    )}
                  </>
                )}
              </div>
            </>
          ) : (
            <div className="detail-body empty-filter">
              {reviewLoading
                ? "Loading the complete review queue and source evidence…"
                : "Select a flagged item."}
            </div>
          )}
        </div>
      </div>

      {pendingConfirmation && (
        <div
          className="overlay show"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !confirmationApplying) {
              setPendingConfirmation(null);
            }
          }}
        >
          <section
            className="modal review-bulk-confirmation"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="review-confirmation-heading"
            aria-describedby="review-confirmation-message"
          >
            <div className="modal-ic">
              <TriangleAlert aria-hidden="true" />
            </div>
            <span className="eyebrow">
              {pendingConfirmation.kind === "bulk"
                ? "Bulk review action"
                : "Unsaved review change"}
            </span>
            <h3 id="review-confirmation-heading">Confirm this change</h3>
            <p id="review-confirmation-message">
              {pendingConfirmation.message}
            </p>
            <div className="modal-actions">
              <button
                className="btn btn-outline"
                type="button"
                disabled={confirmationApplying}
                onClick={() => setPendingConfirmation(null)}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                type="button"
                disabled={confirmationApplying}
                autoFocus
                onClick={() => void confirmPendingAction()}
              >
                {confirmationApplying ? "Applying changes…" : "Confirm"}
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
