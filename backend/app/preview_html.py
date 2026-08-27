"""Accessible HTML using the same publication design as the reviewer preview.

The exported fragment intentionally starts at the publication body. WordPress
supplies the global masthead and footer, while this file keeps the preview's
report card, recommendations, accordion contents, citation and reader.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "publication"


def _project_slug(value: str) -> str:
    project_title = re.split(r"\s*:\s*", value.strip(), maxsplit=1)[0]
    project_title = re.sub(
        r"\s+[-\u2013\u2014]\s+(?:consultation paper|issues paper|final report|report)$",
        "",
        project_title,
        flags=re.IGNORECASE,
    )
    return _slug(project_title)


_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def _month_index(name: str) -> int:
    lowered = name.casefold()
    for index, month_name in enumerate(_MONTH_NAMES, start=1):
        if month_name.startswith(lowered):
            return index
    return 0


def _valid_date_parts(year: int, month: int, day: int) -> bool:
    try:
        datetime(year, month, day)
        return True
    except ValueError:
        return False


def _normalize_published_date_input(value: Any) -> str:
    raw = str(value or "").strip().rstrip(".")
    if not raw:
        return ""
    return re.sub(
        r"^published\s+(?:on\s+)?",
        "",
        re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE),
        flags=re.IGNORECASE,
    ).strip()


def _parse_published_date(value: Any) -> datetime | None:
    """Parse a metadata date field into a datetime, matching the frontend's
    formatPublicationDate (src/lib/publicationFormatting.ts) so both sides
    agree on ISO, day-first numeric, and named-month date formats."""
    normalized = _normalize_published_date_input(value)
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        pass

    day_first_numeric = re.match(
        r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?:[T\s].*)?$", normalized
    )
    if day_first_numeric:
        day, month, year = (int(part) for part in day_first_numeric.groups())
        if _valid_date_parts(year, month, day):
            return datetime(year, month, day)

    day_month_name = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", normalized)
    if day_month_name:
        day_value, month_name, year_value = day_month_name.groups()
        month = _month_index(month_name)
        if month and _valid_date_parts(int(year_value), month, int(day_value)):
            return datetime(int(year_value), month, int(day_value))

    month_name_day = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", normalized)
    if month_name_day:
        month_name, day_value, year_value = month_name_day.groups()
        month = _month_index(month_name)
        if month and _valid_date_parts(int(year_value), month, int(day_value)):
            return datetime(int(year_value), month, int(day_value))

    return None


def _format_published_date(value: Any) -> str:
    parsed = _parse_published_date(value)
    if parsed:
        return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"
    return _normalize_published_date_input(value) or "date not specified"


def _publication_year(value: Any) -> str:
    """Best-effort publication year for a self-citation, independent of the
    document's in-body legal citations (ISBNs, Acts, case names)."""
    parsed = _parse_published_date(value)
    if parsed:
        return str(parsed.year)
    match = re.search(r"\b(19|20)\d{2}\b", _normalize_published_date_input(value))
    return match.group(0) if match else ""


def _recommendation_snippets(sections: list[dict[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for section in sections:
        # A "Key recommendations" callout box commonly lives inside a chapter
        # with an unrelated title (e.g. "Findings"), so box_section/callout
        # blocks are matched on their own title/variant below regardless of
        # whether the parent chapter's title also mentions "recommend".
        section_matches = bool(
            re.search(r"recommend", str(section.get("displayTitle", "")), re.I)
        )
        for block in section.get("blocks", []):
            block_type = str(block.get("type", ""))
            if section_matches and block_type == "paragraph":
                candidates.append(str(block.get("text", "")))
            elif section_matches and block_type == "list":
                candidates.extend(
                    str(item.get("text", "")) for item in block.get("items", [])
                )
            elif block_type in {"box_section", "callout"} and re.search(
                r"recommend",
                f"{block.get('title', '')} {block.get('variant', '')}",
                re.I,
            ):
                for child in block.get("blocks", []):
                    if child.get("type") == "paragraph":
                        candidates.append(str(child.get("text", "")))
                    elif child.get("type") == "list":
                        candidates.extend(
                            str(item.get("text", ""))
                            for item in child.get("items", [])
                        )
    output: list[str] = []
    for value in candidates:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if len(cleaned) >= 24 and cleaned not in output:
            output.append(cleaned)
        if len(output) == 3:
            break
    return output


def _is_chapter(section: dict[str, Any]) -> bool:
    if isinstance(section.get("isChapter"), bool):
        return bool(section["isChapter"])
    return bool(
        re.match(
            r"^\s*(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b|\d+[.)]\s+)",
            str(section.get("displayTitle", "")),
            re.I,
        )
    )


def _major_headings(section: dict[str, Any]) -> list[dict[str, Any]]:
    headings = [
        heading
        for heading in section.get("headings", [])
        if int(heading.get("level", 2)) == 2
    ]
    return sorted(
        headings,
        key=lambda heading: (
            int(heading["tocSequence"])
            if isinstance(heading.get("tocSequence"), int)
            else 1_000_000,
            int(heading.get("page", 0)),
        ),
    )


_FOOTNOTE_CONTEXT_WORDS = {
    "appendix",
    "article",
    "chapter",
    "clause",
    "figure",
    "item",
    "number",
    "option",
    "paragraph",
    "part",
    "page",
    "recommendation",
    "rule",
    "schedule",
    "section",
    "sections",
    "stage",
    "table",
    "version",
    "volume",
}


def _footnote_targets(footnotes: list[dict[str, Any]]) -> dict[str, str]:
    targets: dict[str, str] = {}
    for note in footnotes:
        note_id = str(note.get("id", "")).strip()
        match = re.match(r"footnote-(\d+)(?:-|$)", note_id, re.IGNORECASE)
        if match and match.group(1) not in targets:
            targets[match.group(1)] = note_id
    return targets


def _render_inline_text(value: Any, footnote_targets: dict[str, str]) -> str:
    """Escape text and restore Docling's flattened footnote-reference links."""

    text = str(value or "")
    if not text or not footnote_targets:
        return html.escape(text)

    for number in footnote_targets:
        text = re.sub(
            rf"(?<!\d){re.escape(number)}[ \t]+{re.escape(number)}(?!\d)",
            number,
            text,
        )

    parts: list[str] = []
    cursor = 0
    token_pattern = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
    for match in token_pattern.finditer(text):
        number = match.group(1)
        note_id = footnote_targets.get(number)
        if not note_id:
            continue
        suffix = text[match.end() : match.end() + 2].casefold()
        if suffix in {"st", "nd", "rd", "th"}:
            continue
        if (
            match.start() >= 2
            and text[match.start() - 1] == "."
            and text[match.start() - 2].isdigit()
        ) or (
            match.end() + 1 < len(text)
            and text[match.end()] == "."
            and text[match.end() + 1].isdigit()
        ):
            continue
        preceding = text[: match.start()]
        previous_word = re.search(r"([A-Za-z]+)\s*$", preceding)
        if previous_word and previous_word.group(1).casefold() in _FOOTNOTE_CONTEXT_WORDS:
            continue

        prefix = text[cursor : match.start()]
        # A citation marker belongs to the preceding word or punctuation, so do
        # not preserve extraction whitespace immediately before the superscript.
        prefix = re.sub(r"[ \t]+$", "", prefix)
        parts.append(html.escape(prefix))
        safe_id = html.escape(note_id, quote=True)
        parts.append(
            f'<sup class="footnote-reference"><a href="#{safe_id}" '
            f'role="doc-noteref" aria-label="Footnote {number}">{number}</a></sup>'
        )
        cursor = match.end()
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def _render_table_cell(
    cell: dict[str, Any],
    footnote_targets: dict[str, str],
) -> str:
    tag = "th" if cell.get("columnHeader") or cell.get("rowHeader") else "td"
    scope = (
        ' scope="col"'
        if cell.get("columnHeader")
        else ' scope="row"'
        if cell.get("rowHeader")
        else ""
    )
    rowspan = (
        f' rowspan="{int(cell["rowSpan"])}"'
        if int(cell.get("rowSpan", 1) or 1) > 1
        else ""
    )
    colspan = (
        f' colspan="{int(cell["colSpan"])}"'
        if int(cell.get("colSpan", 1) or 1) > 1
        else ""
    )
    return (
        f"<{tag}{scope}{rowspan}{colspan}>"
        f"{_render_inline_text(cell.get('text', ''), footnote_targets)}</{tag}>"
    )


def _nested_list_tree(
    items: list[dict[str, Any]],
    default_ordered: bool,
) -> list[dict[str, Any]]:
    if not items:
        return []
    levels = [max(0, int(item.get("level", 0) or 0)) for item in items]
    base_level = min(levels)
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, list[dict[str, Any]]]] = [(-1, roots)]
    for raw, raw_level in zip(items, levels, strict=False):
        level = raw_level - base_level
        while stack[-1][0] >= level:
            stack.pop()
        if level > stack[-1][0] + 1:
            level = stack[-1][0] + 1
        node = {
            **raw,
            "ordered": bool(raw.get("ordered", default_ordered)),
            "children": [],
        }
        stack[-1][1].append(node)
        stack.append((level, node["children"]))
    return roots


def _render_list_items(
    nodes: list[dict[str, Any]],
    footnote_targets: dict[str, str],
    start: int | None = None,
) -> str:
    output: list[str] = []
    index = 0
    while index < len(nodes):
        ordered = bool(nodes[index].get("ordered"))
        group: list[dict[str, Any]] = []
        while index < len(nodes) and bool(nodes[index].get("ordered")) == ordered:
            group.append(nodes[index])
            index += 1
        tag = "ol" if ordered else "ul"
        start_attribute = (
            f' start="{max(1, int(start or 1))}"'
            if ordered and start not in (None, 1) and not output
            else ""
        )
        items_html = ""
        for item in group:
            value_attribute = (
                f' value="{int(item["value"])}"'
                if ordered and item.get("value") is not None
                else ""
            )
            items_html += (
                f"<li{value_attribute}>{_render_inline_text(item.get('text', ''), footnote_targets)}"
                f"{_render_list_items(item.get('children', []), footnote_targets)}</li>"
            )
        output.append(
            f'<{tag} class="reader-source-list"{start_attribute}>'
            f"{items_html}</{tag}>"
        )
    return "".join(output)


def _render_numbered_paragraph(
    number: Any,
    text: Any,
    footnote_targets: dict[str, str],
) -> str:
    safe_number = html.escape(str(number or ""))
    return (
        '<div class="reader-numbered-paragraph">'
        f'<span class="reader-paragraph-number" aria-hidden="true">{safe_number}</span>'
        f'<p><span class="sr-only">Paragraph {safe_number}. </span>'
        f"{_render_inline_text(text, footnote_targets)}</p></div>"
    )


def _render_block(
    block: dict[str, Any],
    figure_directory: Path | None,
    footnote_targets: dict[str, str],
) -> str:
    block_type = str(block.get("type", ""))
    if block_type == "heading":
        source_level = int(block.get("level", 2))
        level = 2 if source_level <= 2 else min(6, source_level)
        return (
            f'<h{level} id="{html.escape(str(block.get("id", "")), quote=True)}">'
            f'{html.escape(str(block.get("text", "")))}</h{level}>'
        )
    if block_type == "paragraph":
        if block.get("number"):
            return _render_numbered_paragraph(
                block.get("number"), block.get("text"), footnote_targets
            )
        return f'<p class="docling-paragraph">{_render_inline_text(block.get("text", ""), footnote_targets)}</p>'
    if block_type == "list":
        if block.get("style") == "numbered-paragraphs":
            return '<div class="docling-numbered-group">' + "".join(
                _render_numbered_paragraph(
                    item.get("marker"), item.get("text"), footnote_targets
                )
                for item in block.get("items", [])
            ) + "</div>"
        ordered = block.get("style") == "ordered"
        try:
            start = max(1, int(block.get("start", 1) or 1))
        except (TypeError, ValueError):
            start = 1
        return _render_list_items(
            _nested_list_tree(
                [dict(item) for item in block.get("items", [])],
                ordered,
            ),
            footnote_targets,
            start,
        )
    if block_type in {"box_section", "callout"}:
        box_id = html.escape(str(block.get("id", "box-section")), quote=True)
        variant = re.sub(
            r"[^a-z-]",
            "",
            str(block.get("variant", "information")).casefold(),
        ) or "information"
        content = "".join(
            _render_block(child, figure_directory, footnote_targets)
            for child in block.get("blocks", [])
        )
        return (
            f'<section class="docling-box-section docling-box-section--{variant}" '
            f'aria-labelledby="{box_id}-title">'
            f'<h3 id="{box_id}-title">{html.escape(str(block.get("title", "Box Section")))}</h3>'
            f'<div class="docling-box-section-content">{content}</div></section>'
        )
    if block_type == "table":
        rows = list(block.get("rows", []))
        header_rows = [
            row for row in rows if row and all(cell.get("columnHeader") for cell in row)
        ][:1]
        body_rows = [row for row in rows if row not in header_rows]
        caption = str(block.get("caption", "")).strip()
        caption_html = f"<caption>{html.escape(caption)}</caption>" if caption else ""
        head_html = (
            "<thead>"
            + "".join(
                f"<tr>{''.join(_render_table_cell(cell, footnote_targets) for cell in row)}</tr>"
                for row in header_rows
            )
            + "</thead>"
            if header_rows
            else ""
        )
        body_html = "".join(
            f"<tr>{''.join(_render_table_cell(cell, footnote_targets) for cell in row)}</tr>"
            for row in body_rows
        )
        table_id = html.escape(str(block.get("id", "")), quote=True)
        label = html.escape(caption or "Table", quote=True)
        return (
            f'<div class="docling-table-scroll" tabindex="0" role="region" '
            f'aria-label="{label}; scroll horizontally when needed">'
            f'<table class="docling-table" id="{table_id}">'
            f"{caption_html}{head_html}<tbody>{body_html}</tbody></table></div>"
        )
    if block_type == "footnote":
        return (
            f'<p class="docling-footnote" id="{html.escape(str(block.get("id", "")), quote=True)}" '
            f'role="doc-footnote">{html.escape(str(block.get("text", "")))}</p>'
        )
    if block_type == "figure":
        caption = html.escape(str(block.get("caption", "Figure")))
        image_key = str(block.get("imageKey", ""))
        image_path = (
            figure_directory / f"figure-{image_key}.png"
            if figure_directory is not None and image_key
            else None
        )
        # A relative filename, not a data URI: figure PNGs are written as
        # siblings of accessible.html in the document's export directory, and
        # a linked file keeps the export small enough for AI browsing tools
        # and crawlers to actually fetch, unlike inlining every image (a
        # handful of figures easily pushes a single-file export past 4MB).
        image_uri = f"figure-{image_key}.png" if image_path is not None and image_path.is_file() else ""
        visual = (
            f'<img class="docling-figure-image" src="{image_uri}" alt="{caption}">'
            if image_uri
            else (
                f'<div class="docling-figure-placeholder" role="img" '
                f'aria-label="{caption}"><span>The original figure preview is unavailable.</span></div>'
            )
        )
        return (
            f'<figure class="docling-figure" id="{html.escape(str(block.get("id", "")), quote=True)}">'
            f"{visual}<figcaption>{caption}</figcaption></figure>"
        )
    if block_type == "caption":
        return f'<p class="docling-caption">{html.escape(str(block.get("text", "")))}</p>'
    if block_type == "formula":
        return (
            '<div class="docling-formula" role="math" aria-label="Formula">'
            f'{html.escape(str(block.get("text", "")))}</div>'
        )
    if block_type == "checkbox":
        checked = " checked" if block.get("checked") else ""
        return (
            '<label class="docling-checkbox">'
            f'<input type="checkbox"{checked} disabled>'
            f'<span>{html.escape(str(block.get("text", "")))}</span></label>'
        )
    if block_type == "group":
        items = "".join(
            f"<p>{html.escape(str(item.get('text', '')))}</p>"
            for item in block.get("items", [])
        )
        return (
            '<fieldset class="docling-group">'
            f'<legend>{html.escape(str(block.get("label", "Document details")))}</legend>'
            f"{items}</fieldset>"
        )
    return ""


PREVIEW_STYLE = r"""
.vlrc-publication-embed,.vlrc-publication-embed *{box-sizing:border-box}
.vlrc-publication-embed{--blue:#005493;--blue-dark:#003f73;--blue-tint:#f3f7fa;--red:#b52b38;--ink:#1c1c1c;--ink-2:#454545;--muted:#6b6b6b;--line:#d5d5d5;--line-2:#b8b8b8;--surface-2:#f6f6f6;--radius:6px;width:100%;max-width:none;background:#fff;color:var(--ink);font-family:Arial,"Helvetica Neue",sans-serif;font-size:16px;line-height:1.6}
.vlrc-publication-embed a{overflow-wrap:anywhere}
.vlrc-publication-embed a:focus-visible,.vlrc-publication-embed button:focus-visible,.vlrc-publication-embed input:focus-visible,.vlrc-publication-embed [tabindex="-1"]:focus-visible{outline:3px solid #73a9cf;outline-offset:3px}
.vlrc-publication-embed [hidden]{display:none!important}
.vlrc-publication-embed .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.vlrc-publication-embed .skip-link{position:absolute;left:1rem;top:-6rem;z-index:10;padding:.75rem 1rem;background:#fff;color:var(--blue);font-weight:700}
.vlrc-publication-embed .skip-link:focus{top:1rem}
.vlrc-publication-embed .vlrc-preview-body{width:100%;padding:22px clamp(18px,3vw,38px) 42px;container-type:inline-size}
.vlrc-publication-embed .preview-report-card-shell,.vlrc-publication-embed .preview-publication-main{min-width:0}
.vlrc-publication-embed .preview-publication-main{padding:28px 0 0}
.vlrc-publication-embed .report-card{display:grid;width:100%;grid-template-columns:minmax(150px,200px) minmax(0,1fr);gap:28px;padding:26px;border:1px solid var(--line);border-radius:var(--radius);background:#fff}
.vlrc-publication-embed .report-cover-link{align-self:start}
.vlrc-publication-embed .report-cover-link img{display:block;width:100%;height:auto;border:1px solid var(--line-2);box-shadow:0 8px 24px rgba(12,45,72,.12)}
.vlrc-publication-embed .report-card-content{min-width:0}
.vlrc-publication-embed .report-card-status-row{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px;color:var(--muted);font-size:12px;font-weight:700}
.vlrc-publication-embed .official-source-badge{display:inline-flex;align-items:center;gap:6px;color:#176a62;font-weight:800}
.vlrc-publication-embed .report-card-title{margin:0;color:#0c2d48;font-size:clamp(28px,4vw,38px);font-weight:800;line-height:1.12;letter-spacing:-.025em}
.vlrc-publication-embed .report-publisher{margin:7px 0 14px;color:#155d91;font-weight:800}
.vlrc-publication-embed .report-summary{max-width:780px;margin:0 0 20px;color:#465564;font-size:16px}
.vlrc-publication-embed .report-card-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:0 0 18px;border-block:1px solid var(--line)}
.vlrc-publication-embed .report-card-meta>div{padding:12px 16px 12px 0}
.vlrc-publication-embed .report-card-meta>div+div{padding-left:16px;border-left:1px solid var(--line)}
.vlrc-publication-embed .report-card-meta dt{color:var(--muted);font-size:11px;font-weight:800;letter-spacing:.05em;text-transform:uppercase}
.vlrc-publication-embed .report-card-meta dd{margin:3px 0 0;font-size:13px;font-weight:700}
.vlrc-publication-embed .topic-list{display:flex;flex-wrap:wrap;gap:7px;padding:0;margin:0 0 22px;list-style:none}
.vlrc-publication-embed .topic-list li{padding:4px 9px;border-radius:999px;background:#eaf2f7;color:#123b5d;font-size:12px;font-weight:800}
.vlrc-publication-embed .report-card-actions{display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px}
.vlrc-publication-embed .button{display:inline-flex;min-height:46px;align-items:center;justify-content:center;padding:10px 16px;border:1px solid #123b5d;border-radius:7px;font-size:13px;font-weight:800;line-height:1.2;text-decoration:none}
.vlrc-publication-embed .button-primary{background:#123b5d;color:#fff}
.vlrc-publication-embed .button-secondary{background:#fff;color:#123b5d}
.vlrc-publication-embed .text-action{color:var(--blue);font-size:12px;font-weight:800;text-decoration:underline;text-underline-offset:3px}
.vlrc-publication-embed .key-recommendations{padding:22px 0;margin:22px 0;border-block:1px solid var(--line)}
.vlrc-publication-embed .eyebrow{color:var(--red);font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
.vlrc-publication-embed .key-recommendations h2{margin:3px 0 0;color:var(--blue-dark);font-size:22px}
.vlrc-publication-embed .key-recommendations>div{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin-top:13px}
.vlrc-publication-embed .key-recommendations article{padding:13px;border-radius:8px;background:var(--blue-tint)}
.vlrc-publication-embed .key-recommendations article strong{color:var(--red);font:700 12px/1 monospace}
.vlrc-publication-embed .key-recommendations article p{margin:8px 0 0;font-size:11.5px;line-height:1.5}
.vlrc-publication-embed .vlrc-contents{margin-top:34px}
.vlrc-publication-embed .contents-heading-row{display:flex;align-items:flex-end;justify-content:space-between;gap:14px}
.vlrc-publication-embed .contents-heading-row h2{margin:3px 0 12px;color:var(--blue);font-size:22px}
.vlrc-publication-embed .vlrc-accordion ul{margin:0;padding:0;list-style:none}
.vlrc-publication-embed .vlrc-direct-item,.vlrc-publication-embed .vlrc-accordion-item{border-bottom:1px solid var(--line-2)}
.vlrc-publication-embed .vlrc-direct-item>a,.vlrc-publication-embed .vlrc-direct-item>label,.vlrc-publication-embed .vlrc-accordion-item>summary{display:flex;width:100%;min-height:48px;align-items:center;justify-content:space-between;gap:16px;padding:12px 14px;border:0;border-radius:0;background:#fff;color:var(--ink);font:700 13px/1.35 Arial,"Helvetica Neue",sans-serif;text-align:left;text-decoration:none}
.vlrc-publication-embed .vlrc-accordion-item>summary{cursor:pointer;list-style:none}
.vlrc-publication-embed .vlrc-accordion-item>summary::-webkit-details-marker{display:none}
.vlrc-publication-embed .vlrc-direct-item>a:hover,.vlrc-publication-embed .vlrc-direct-item>label:hover,.vlrc-publication-embed .vlrc-accordion-item>summary:hover{background:#f4f7fa;color:var(--blue-dark)}
.vlrc-publication-embed .accordion-chevron{color:var(--blue);font-size:17px;transition:transform .18s ease}
.vlrc-publication-embed .vlrc-accordion-item[open]>summary{background:var(--blue);color:#fff}
.vlrc-publication-embed .vlrc-accordion-item[open] .accordion-chevron{color:#fff;transform:rotate(180deg)}
.vlrc-publication-embed .vlrc-accordion-item:not([open])>.vlrc-accordion-panel{display:none}
.vlrc-publication-embed .vlrc-accordion-item[open]>.vlrc-accordion-panel{display:block;max-height:none;overflow:visible;border-left:3px solid #8bb1cf;background:#fbfbfa}
.vlrc-publication-embed .vlrc-accordion-panel li{border-bottom:1px solid #c7cbd0}
.vlrc-publication-embed .vlrc-accordion-panel li:last-child{border-bottom:0}
.vlrc-publication-embed .vlrc-accordion-panel a,.vlrc-publication-embed .vlrc-accordion-panel label{display:block;padding:11px 18px 11px 24px;color:#3f4650;background:#fbfbfa;font-size:12.5px;text-decoration:none}
.vlrc-publication-embed .vlrc-accordion-panel .vlrc-read-full a,.vlrc-publication-embed .vlrc-accordion-panel .vlrc-read-full label{background:#eef3f8;color:var(--blue);font-weight:700}
.vlrc-publication-embed .preview-citation-card{display:flex;align-items:flex-start;gap:12px;padding:14px 16px;margin-top:22px;border:1px solid var(--line);border-radius:8px;background:var(--surface-2)}
.vlrc-publication-embed .preview-citation-card h2{margin:0;color:var(--blue-dark);font-size:13px}
.vlrc-publication-embed .preview-citation-card p,.vlrc-publication-embed .preview-citation-card blockquote{margin:4px 0 0;color:var(--ink-2);font-size:12px;line-height:1.5}
.vlrc-publication-embed .vlrc-view-toggle{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.vlrc-publication-embed .vlrc-view-label{cursor:pointer}
.vlrc-publication-embed .vlrc-view-label:focus-visible{outline:3px solid #73a9cf;outline-offset:3px}
.vlrc-publication-embed .vlrc-publication-views #publication-landing,.vlrc-publication-embed .vlrc-publication-views .vlrc-reader{display:none}
.vlrc-publication-embed .vlrc-publication-readers{display:contents}
.vlrc-publication-embed .vlrc-reader{width:100%;padding:34px clamp(18px,3vw,38px) 38px;scroll-margin-top:20px}
.vlrc-publication-embed .vlrc-reader-breadcrumb{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:26px;padding-bottom:18px;border-bottom:1px solid var(--line);color:var(--muted);font-size:12px}
.vlrc-publication-embed .vlrc-reader-breadcrumb a,.vlrc-publication-embed .vlrc-reader-breadcrumb label{color:var(--blue);font-weight:700;text-decoration:underline;text-underline-offset:3px}
.vlrc-publication-embed .vlrc-reader-layout{display:grid;grid-template-columns:190px minmax(0,1fr);gap:34px;align-items:start}
.vlrc-publication-embed .vlrc-reader-nav{position:sticky;top:22px;max-height:calc(100vh - 44px);overflow-y:auto;padding:17px 16px;border-top:4px solid var(--blue);background:#f4f6f8}
.vlrc-publication-embed .vlrc-reader-nav h2{margin:0 0 12px;font-size:14px}
.vlrc-publication-embed .vlrc-reader-nav ul{margin:0;padding:0;list-style:none}
.vlrc-publication-embed .vlrc-reader-nav li+li{border-top:1px solid #d6dae0}
.vlrc-publication-embed .vlrc-reader-nav a{display:block;padding:10px 3px;border-left:3px solid transparent;color:var(--ink-2);font-size:12px;line-height:1.35;text-decoration:none}
.vlrc-publication-embed .vlrc-reader-nav a[aria-current="location"]{padding-left:9px;border-left-color:var(--blue);background:#e8eef4;color:var(--blue-dark);font-weight:700}
.vlrc-publication-embed .vlrc-reader-nav .heading-level-3 a{padding-left:13px;font-size:11.5px;font-weight:600}
.vlrc-publication-embed .vlrc-reader-nav .heading-level-4 a{padding-left:22px;font-size:11px}
.vlrc-publication-embed .vlrc-reader-nav .heading-level-5 a{padding-left:31px;color:#5d6672;font-size:10.5px}
.vlrc-publication-embed .vlrc-reader-content{min-width:0;max-width:74ch}
.vlrc-publication-embed .chapter-label{color:var(--red);font-size:11px;font-weight:700;letter-spacing:.13em;text-transform:uppercase}
.vlrc-publication-embed .vlrc-reader-content>h1{margin:8px 0 30px;color:var(--blue);font-size:clamp(30px,4.2vw,44px);font-weight:800;line-height:1.08;letter-spacing:-.03em}
.vlrc-publication-embed .docling-content-blocks>h2{scroll-margin-top:18px;margin:38px 0 16px;color:var(--blue);font-size:24px;line-height:1.2}
.vlrc-publication-embed .docling-content-blocks>h3{scroll-margin-top:18px;margin:28px 0 11px;color:var(--ink);font-size:17px;line-height:1.3}
.vlrc-publication-embed .docling-content-blocks>h4{scroll-margin-top:18px;margin:22px 0 9px;color:var(--ink-2);font-size:14px;line-height:1.4}
.vlrc-publication-embed .docling-content-blocks>h5{scroll-margin-top:18px;margin:19px 0 8px;color:#4d5865;font-size:12.5px;line-height:1.45;letter-spacing:.012em}
.vlrc-publication-embed .docling-paragraph{margin:0 0 15px;color:var(--ink-2);font-size:14px;line-height:1.72}
.vlrc-publication-embed .reader-numbered-paragraph{display:grid;grid-template-columns:minmax(3.5rem,max-content) minmax(0,1fr);gap:10px;margin-bottom:15px;color:var(--ink-2);font-size:14px;line-height:1.72}
.vlrc-publication-embed .reader-paragraph-number{color:var(--red);font:700 11.5px/1.9 monospace}
.vlrc-publication-embed .reader-numbered-paragraph p{margin:0}
.vlrc-publication-embed .reader-source-list{margin:8px 0 17px 52px;padding-left:20px;color:var(--ink-2);font-size:14px;line-height:1.65}
.vlrc-publication-embed ul.reader-source-list{list-style:disc outside}
.vlrc-publication-embed ol.reader-source-list{list-style:decimal outside}
.vlrc-publication-embed .reader-source-list .reader-source-list{margin:6px 0 4px}
.vlrc-publication-embed .docling-box-section{margin:28px 0;overflow:hidden;border:1px solid #b8bec6;border-left:5px solid var(--blue);border-radius:4px;background:#f3f5f7}
.vlrc-publication-embed .docling-box-section>h3{margin:0;padding:12px 18px;border-bottom:1px solid #c9cdd2;background:#dfe4e9;color:#111;font-size:17px;line-height:1.3}
.vlrc-publication-embed .docling-box-section-content{padding:18px 22px 8px}
.vlrc-publication-embed .docling-box-section-content .reader-source-list{margin:8px 0 17px;padding-left:1.5rem}
.vlrc-publication-embed .docling-box-section--recommendations{border-color:#111}
.vlrc-publication-embed .docling-box-section--recommendations>h3{background:#050505;color:#fff;text-transform:uppercase}
.vlrc-publication-embed .docling-table-scroll{max-width:100%;margin:24px 0;overflow-x:auto;border:1px solid #ccd1d8}
.vlrc-publication-embed .docling-table{width:100%;border-collapse:collapse;color:#2f3743;font-size:12px}
.vlrc-publication-embed .docling-table caption{padding:12px 14px;background:#e8eef4;font-weight:700;text-align:left}
.vlrc-publication-embed .docling-table th,.vlrc-publication-embed .docling-table td{min-width:90px;padding:9px 10px;border:1px solid #ccd1d8;text-align:left;vertical-align:top}
.vlrc-publication-embed .docling-table th{background:#f2f5f8}
.vlrc-publication-embed .docling-figure{margin:26px 0}
.vlrc-publication-embed .docling-figure-image{display:block;max-width:100%;width:auto;height:auto;margin:0 auto;border:1px solid var(--line);box-shadow:0 7px 24px rgba(22,35,61,.12)}
.vlrc-publication-embed .docling-figure-placeholder{display:grid;min-height:150px;place-items:center;border:2px dashed var(--line-2);background:#f4f6f8;color:var(--muted);font-size:12px}
.vlrc-publication-embed .docling-figure figcaption,.vlrc-publication-embed .docling-caption{margin:8px 0 18px;color:var(--muted);font-size:12px}
.vlrc-publication-embed .docling-formula{margin:18px 0;padding:14px 16px;border:1px solid var(--line);background:var(--surface-2);font-family:monospace;font-size:13px;white-space:pre-wrap}
.vlrc-publication-embed .docling-footnote{padding-left:12px;border-left:3px solid var(--line-2);color:var(--ink-2);font-size:.92em}
.vlrc-publication-embed .footnote-reference{position:relative;top:-.38em;font-size:.72em;line-height:0;vertical-align:baseline}
.vlrc-publication-embed .footnote-reference a{color:var(--blue);font-weight:700;text-decoration:none}
.vlrc-publication-embed .footnote-reference a:hover,.vlrc-publication-embed .footnote-reference a:focus{text-decoration:underline;text-underline-offset:2px}
.vlrc-publication-embed .reader-footnotes li{scroll-margin-top:20px}
.vlrc-publication-embed .reader-footnotes{margin-top:38px;padding-top:18px;border-top:1px solid #c9cdd4}
.vlrc-publication-embed .reader-footnotes summary{cursor:pointer;color:var(--blue);font-size:14px;font-weight:700}
.vlrc-publication-embed .reader-footnotes ol{padding-left:24px;color:var(--ink-2);font-size:11.5px;line-height:1.6}
.vlrc-publication-embed .reader-pagination{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:28px;padding-top:18px;border-top:1px solid #d5d8de}
.vlrc-publication-embed .reader-pagination>a,.vlrc-publication-embed .reader-pagination>label,.vlrc-publication-embed .pagination-disabled{display:block;padding:13px 14px;border:1px solid #bfc5ce;background:#fff;color:var(--blue);font-size:12.5px;font-weight:700;text-decoration:none}
.vlrc-publication-embed .reader-pagination>a:last-child,.vlrc-publication-embed .reader-pagination>label:last-child,.vlrc-publication-embed .pagination-disabled:last-child{text-align:right}
.vlrc-publication-embed .reader-pagination span{display:block;color:var(--muted);font-size:10.5px;font-weight:500}
.vlrc-publication-embed .pagination-disabled{background:#f4f5f6;color:var(--muted)}
@media(max-width:900px){.vlrc-publication-embed .vlrc-reader-layout{grid-template-columns:1fr}.vlrc-publication-embed .vlrc-reader-nav{position:static}.vlrc-publication-embed .vlrc-reader-nav ul{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}}
@media(max-width:760px){.vlrc-publication-embed .report-card{grid-template-columns:1fr}.vlrc-publication-embed .report-cover-link{width:min(52vw,190px)}.vlrc-publication-embed .report-card-meta{grid-template-columns:1fr}.vlrc-publication-embed .report-card-meta>div,.vlrc-publication-embed .report-card-meta>div+div{padding:9px 0;border-left:0;border-top:1px solid var(--line)}.vlrc-publication-embed .report-card-actions{align-items:stretch;flex-direction:column}.vlrc-publication-embed .key-recommendations>div{grid-template-columns:1fr}.vlrc-publication-embed .reader-pagination{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){.vlrc-publication-embed{scroll-behavior:auto}}
@media print{.vlrc-publication-embed #publication-landing{display:block!important}.vlrc-publication-embed .vlrc-reader{display:block!important;break-before:page}.vlrc-publication-embed .reader-pagination,.vlrc-publication-embed .vlrc-reader-nav{display:none!important}.vlrc-publication-embed .vlrc-reader-layout{display:block}}
"""


def build_accessible_html(
    document_id: str,
    publication: dict[str, Any],
    metadata: dict[str, Any],
    json_ld: dict[str, Any],
    cover_path: Path,
    logo_path: Path,
    figure_directory: Path | None = None,
    chat_api_base: str = "",
) -> str:
    del logo_path  # The host website supplies the global masthead.
    sections = list(publication.get("sections", []))
    raw_title = str(
        metadata.get("title")
        or publication.get("sourceName")
        or "Accessible document"
    )
    title = html.escape(raw_title)
    publisher = html.escape(
        str(metadata.get("publisher") or "Victorian Law Reform Commission")
    )
    jurisdiction_value = str(metadata.get("jurisdiction") or "").strip()
    jurisdiction = html.escape(jurisdiction_value or "Not specified")
    published_date = html.escape(
        _format_published_date(
            metadata.get("published_date") or metadata.get("publishedDate")
        )
    )
    pages = int((publication.get("stats") or {}).get("pages", 0) or 0)
    summary_values = [
        str(value).strip()
        for value in publication.get("summary", [])
        if str(value).strip()
    ]
    summary = html.escape(
        summary_values[0]
        if summary_values
        else f"This publication presents the reviewed content of {raw_title}."
    )
    # `metadata.citations` holds legal citations found in the document body
    # (ISBNs, Acts, case names) — not a citation for the report itself — so
    # "Cite this report" is synthesized from the report's own metadata.
    raw_publisher = str(metadata.get("publisher") or "Victorian Law Reform Commission")
    publication_year = _publication_year(
        metadata.get("published_date") or metadata.get("publishedDate")
    )
    citation = html.escape(
        f"{raw_publisher}, {raw_title} (Report, {publication_year})"
        if publication_year
        else f"{raw_publisher}, {raw_title}"
    )
    configured_project_url = str(
        metadata.get("project_url") or metadata.get("projectUrl") or ""
    ).strip()
    if (
        configured_project_url.startswith("/")
        and not configured_project_url.startswith("//")
    ) or re.match(r"^https?://", configured_project_url, re.I):
        raw_project_url = configured_project_url
    else:
        raw_project_url = f"/project/{_project_slug(raw_title)}/"
    project_url = html.escape(raw_project_url, quote=True)
    source_url = f"/api/documents/{html.escape(document_id, quote=True)}/source"
    # Relative filename rather than a data URI, same reasoning as figures
    # above: cover.png is written as a sibling of accessible.html.
    cover_uri = cover_path.name if cover_path.is_file() else ""
    cover_html = (
        f'<img src="{cover_uri}" alt="Cover of {title}">'
        if cover_uri
        else '<span class="sr-only">Publication cover unavailable</span>'
    )
    section_view_ids = [
        f"vlrc-view-{index}-{_slug(str(section.get('id', index)))}"
        for index, section in enumerate(sections)
    ]
    first_view_id = section_view_ids[0] if section_view_ids else "vlrc-view-landing"

    recommendations = _recommendation_snippets(sections)
    recommendations_html = ""
    if recommendations:
        cards = "".join(
            f"<article><strong>{index:02d}</strong><p>{html.escape(value)}</p></article>"
            for index, value in enumerate(recommendations, start=1)
        )
        recommendations_html = (
            '<section class="key-recommendations" aria-labelledby="recommendations-heading">'
            '<span class="eyebrow">At a glance</span>'
            '<h2 id="recommendations-heading">Key recommendations</h2>'
            f"<div>{cards}</div></section>"
        )

    accordion_items: list[str] = []
    for section_index, section in enumerate(sections):
        section_id = html.escape(str(section["id"]), quote=True)
        section_title = html.escape(str(section["displayTitle"]))
        view_id = section_view_ids[section_index]
        if not _is_chapter(section):
            accordion_items.append(
                '<div class="vlrc-direct-item">'
                f'<label class="vlrc-view-label" for="{view_id}" role="button" tabindex="0">'
                f'<span>{section_title}</span><span aria-hidden="true">›</span>'
                "</label></div>"
            )
            continue
        panel_id = f"{section_id}-subsections"
        child_links = [
            f'<li class="vlrc-read-full"><label class="vlrc-view-label" '
            f'for="{view_id}" role="button" tabindex="0">'
            "Read full section</label></li>"
        ]
        child_links.extend(
            f'<li><label class="vlrc-view-label" for="{view_id}" role="button" tabindex="0">'
            f'{html.escape(str(heading["text"]))}</label></li>'
            for heading in _major_headings(section)
        )
        accordion_items.append(
            '<details class="vlrc-accordion-item">'
            f'<summary aria-controls="{panel_id}">'
            f"<span>{section_title}</span>"
            '<span class="accordion-chevron" aria-hidden="true">⌄</span>'
            "</summary>"
            f'<div class="vlrc-accordion-panel" id="{panel_id}">'
            f'<ul>{"".join(child_links)}</ul></div></details>'
        )
    accordion_html = "".join(accordion_items)

    def render_footnotes(section: dict[str, Any]) -> str:
        footnotes = section.get("footnotes", [])
        if not footnotes:
            return ""
        notes = "".join(
            f'<li id="{html.escape(str(note["id"]), quote=True)}">'
            f'{html.escape(str(note["text"]))}</li>'
            for note in footnotes
        )
        return (
            '<details class="reader-footnotes">'
            f"<summary>References and footnotes ({len(footnotes)})</summary>"
            f"<ol>{notes}</ol></details>"
        )

    def render_reader(section: dict[str, Any], index: int) -> str:
        section_id = html.escape(str(section["id"]), quote=True)
        section_title = html.escape(str(section["displayTitle"]))
        heading_links = "".join(
            f'<li class="heading-level-{min(5, max(2, int(heading.get("level", 2))))}">'
            f'<a href="#{html.escape(str(heading["id"]), quote=True)}">'
            f'{html.escape(str(heading["text"]))}</a></li>'
            for heading in section.get("headings", [])
        )
        previous = (
            f'<label class="vlrc-view-label" for="{section_view_ids[index - 1]}" '
            f'role="button" tabindex="0"><span>Previous</span>'
            f'{html.escape(str(sections[index - 1]["displayTitle"]))}</label>'
            if index > 0
            else '<span class="pagination-disabled"><span>Previous</span>Beginning of document</span>'
        )
        following = (
            f'<label class="vlrc-view-label" for="{section_view_ids[index + 1]}" '
            f'role="button" tabindex="0"><span>Next</span>'
            f'{html.escape(str(sections[index + 1]["displayTitle"]))}</label>'
            if index + 1 < len(sections)
            else '<span class="pagination-disabled"><span>Next</span>End of document</span>'
        )
        footnote_targets = _footnote_targets(list(section.get("footnotes", [])))
        blocks_html = "".join(
            _render_block(block, figure_directory, footnote_targets)
            for block in section.get("blocks", [])
        )
        return (
            f'<section class="vlrc-reader" id="reader-{section_id}" '
            f'tabindex="-1" aria-labelledby="reader-title-{section_id}">'
            '<nav class="vlrc-reader-breadcrumb" aria-label="Breadcrumb">'
            '<label class="vlrc-view-label" for="vlrc-view-landing" role="button" '
            'tabindex="0">← Back to table of contents</label>'
            '<span aria-hidden="true">›</span>'
            f'<span aria-current="page">{section_title}</span></nav>'
            '<div class="vlrc-reader-layout">'
            '<nav class="vlrc-reader-nav" aria-label="In this section">'
            f"<h2>In this section</h2><ul>{heading_links}</ul></nav>"
            '<div class="vlrc-reader-content">'
            f'<div class="chapter-label">{title}</div>'
            f'<h1 id="reader-title-{section_id}" tabindex="-1">{section_title}</h1>'
            f'<div class="docling-content-blocks">{blocks_html}</div>'
            f"{render_footnotes(section)}"
            f'<nav class="reader-pagination" aria-label="Document section pagination">'
            f"{previous}{following}</nav></div></div></section>"
        )

    readers_html = "".join(
        render_reader(section, index) for index, section in enumerate(sections)
    )
    view_toggles = (
        '<input class="vlrc-view-toggle" type="radio" name="vlrc-publication-view" '
        'id="vlrc-view-landing" checked aria-label="Show publication overview">'
        + "".join(
            f'<input class="vlrc-view-toggle" type="radio" '
            f'name="vlrc-publication-view" id="{view_id}" '
            f'aria-label="Read {html.escape(str(section["displayTitle"]), quote=True)}">'
            for view_id, section in zip(section_view_ids, sections, strict=False)
        )
    )
    view_style = (
        ".vlrc-publication-embed #vlrc-view-landing:checked~.vlrc-publication-views "
        "#publication-landing{display:block}"
        + "".join(
            f'.vlrc-publication-embed #{view_id}:checked~.vlrc-publication-views '
            f'#reader-{html.escape(str(section["id"]), quote=True)}{{display:block}}'
            for view_id, section in zip(section_view_ids, sections, strict=False)
        )
    )
    topics = [value for value in (jurisdiction_value, "Law reform") if value]
    topics_html = "".join(f"<li>{html.escape(value)}</li>" for value in dict.fromkeys(topics))
    safe_json_ld = (
        json.dumps(json_ld, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    # The embeddable chat widget (see src/widget/embed.ts, built by
    # `npm run build:widget`) is only wired in when KONVERTER_PUBLIC_API_URL
    # is set \u2014 without an absolute backend origin, a page pasted into a
    # site like WordPress would have no reachable URL to point the widget
    # at, so it's silently omitted rather than baked in broken.
    chat_widget_html = ""
    if chat_api_base:
        origin = chat_api_base.rstrip("/")
        widget_config = (
            json.dumps(
                {"documentId": document_id, "apiBase": f"{origin}/api"},
                ensure_ascii=False,
            )
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )
        widget_src = html.escape(
            f"{origin}/static/widget/konverter-chat-widget.js", quote=True
        )
        chat_widget_html = (
            f"<script>window.__KONVERTER_CHAT__={widget_config};</script>"
            f'<script src="{widget_src}" defer></script>'
        )

    return f"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script type="application/ld+json">{safe_json_ld}</script>
<style>{PREVIEW_STYLE}{view_style}</style>
</head>
<body>
<div class="vlrc-publication-embed" data-konverter-publication>
  {view_toggles}
  <a class="skip-link" href="#publication-title">Skip to publication content</a>
  <div class="vlrc-publication-views">
  <section class="vlrc-preview-body" id="publication-landing" aria-labelledby="publication-title">
    <div class="preview-report-card-shell">
      <section class="report-card preview-report-card" aria-labelledby="publication-title" itemscope itemtype="https://schema.org/Report">
        <div class="report-cover-link">{cover_html}</div>
        <div class="report-card-content">
          <div class="report-card-status-row"><span class="official-source-badge">✓ Reviewed source</span><span>Reviewed publication</span></div>
          <h1 class="report-card-title" id="publication-title" itemprop="headline" tabindex="-1">{title}</h1>
          <p class="report-publisher">{publisher}</p>
          <p class="report-summary">{summary}</p>
          <dl class="report-card-meta">
            <div><dt>Published</dt><dd>{published_date}</dd></div>
            <div><dt>Length</dt><dd>{pages} pages</dd></div>
            <div><dt>Jurisdiction</dt><dd>{jurisdiction}</dd></div>
          </dl>
          <ul class="topic-list" aria-label="Report topics">{topics_html}</ul>
          <div class="report-card-actions" aria-label="Ways to use {title}">
            <label class="button button-primary vlrc-view-label" for="{first_view_id}" role="button" tabindex="0">Read online</label>
            <a class="button button-secondary" href="{source_url}">Download PDF</a>
            <a class="button button-secondary" href="{project_url}">Go to Project</a>
            <a class="text-action" href="#report-contents">View report sections</a>
            <a class="text-action" href="#preview-citation">View citation</a>
          </div>
        </div>
      </section>
    </div>
    <div class="preview-publication-main">
      {recommendations_html}
      <section class="vlrc-contents" id="report-contents" aria-labelledby="contents-heading">
        <div class="contents-heading-row">
          <div><span class="eyebrow">Full report</span><h2 id="contents-heading">Table of contents</h2></div>
        </div>
        <div class="vlrc-accordion" aria-label="Complete report chapters">{accordion_html}</div>
      </section>
      <section class="preview-citation-card" id="preview-citation" aria-labelledby="preview-citation-heading">
        <div><span class="eyebrow">Source and citation</span><h2 id="preview-citation-heading">Cite this report</h2><blockquote>{citation}</blockquote><p>Published by {publisher}.</p></div>
      </section>
    </div>
  </section>
  <div class="vlrc-publication-readers" aria-label="Full publication content">{readers_html}</div>
  </div>
</div>
{chat_widget_html}
</body>
</html>"""
