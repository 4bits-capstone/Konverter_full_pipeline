from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or "section"


def _project_slug(value: str) -> str:
    """Derive the parent project slug from a publication title.

    VLRC publication titles commonly append the publication type after a colon,
    for example ``Project name: Consultation Paper``.  The project page keeps
    only the title before that suffix.
    """
    project_title = re.split(r"\s*:\s*", value.strip(), maxsplit=1)[0]
    project_title = re.sub(
        r"\s+[\-\u2013\u2014]\s+(?:consultation paper|issues paper|final report|report)$",
        "",
        project_title,
        flags=re.IGNORECASE,
    )
    return _slug(project_title)


def _unique_slug(value: str, counts: Counter[str]) -> str:
    base = _slug(value)
    counts[base] += 1
    return base if counts[base] == 1 else f"{base}-{counts[base]}"


def _split_lines(value: str) -> list[str]:
    return [
        re.sub(r"^[•\-–]\s*", "", line).strip()
        for line in value.splitlines()
        if re.sub(r"^[•\-–]\s*", "", line).strip()
    ]


_ORDERED_LIST_MARKER = re.compile(
    r"^(?P<marker>\((?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\)|"
    r"(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)])\s+"
)
_BULLET_LIST_MARKER = re.compile(r"^(?P<marker>[•\-–*·])\s+")


def _parsed_list_entry(value: str) -> dict[str, Any] | None:
    raw = str(value).replace("\t", "  ").strip()
    ordered = _ORDERED_LIST_MARKER.match(raw)
    bullet = _BULLET_LIST_MARKER.match(raw)
    match = ordered or bullet
    marker = match.group("marker") if match else ""
    text = raw[match.end() :].strip() if match else raw
    if not text:
        return None
    marker_number = re.fullmatch(r"\(?(\d+)[.)]", marker)
    return {
        "text": text,
        "marker": marker,
        "enumerated": ordered is not None,
        "level": 0,
        "value": int(marker_number.group(1)) if marker_number else None,
    }


def _section_key(value: str) -> str:
    return (
        re.sub(
            r"^(?:chapter\s+)?\d+\.\s*",
            "",
            value.strip(),
            flags=re.IGNORECASE,
        )
        .strip()
        .casefold()
    )


def _is_chapter_title(value: str) -> bool:
    """Only numbered chapters/parts use collapsible landing navigation."""
    return bool(
        re.match(
            r"^\s*(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b|\d+[.)]\s+)",
            value,
            re.IGNORECASE,
        )
    )


def _summary_from_values(values: list[str], max_chars: int) -> str:
    """Build a compact description and prefer complete sentences."""
    sentences: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized):
            sentence = sentence.strip()
            key = sentence.casefold()
            if len(sentence) < 35 or key in seen:
                continue
            seen.add(key)
            candidate = " ".join([*sentences, sentence])
            if len(candidate) > max_chars:
                break
            sentences.append(sentence)
        if sentences and len(" ".join(sentences)) >= max_chars * 0.65:
            break
    if sentences:
        return " ".join(sentences)

    normalized = re.sub(r"\s+", " ", " ".join(values)).strip()
    if len(normalized) <= max_chars:
        return normalized
    sentence_end = max(
        normalized.rfind(". ", 0, max_chars),
        normalized.rfind("? ", 0, max_chars),
        normalized.rfind("! ", 0, max_chars),
    )
    if sentence_end >= max_chars // 2:
        return normalized[: sentence_end + 1]
    word_end = normalized.rfind(" ", 0, max_chars - 1)
    return f"{normalized[: max(word_end, max_chars - 2)].rstrip()}…"


def _summary_heading(value: str) -> str:
    value = re.sub(
        r"^\s*(?:(?:chapter|section)\s+)?(?:\d+(?:\.\d+)*|[A-Z])(?:[.):\-–—]|\s)+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _heading_level(label: str) -> int | None:
    match = re.fullmatch(r"section_header_([1-5])", label)
    return int(match.group(1)) if match else None


def _publication_summary(
    blocks: list[dict[str, Any]],
    source_name: str,
    max_chars: int = 600,
) -> str:
    ordered = sorted(
        (block for block in blocks if not block.get("removed")),
        key=lambda value: int(value.get("order", 0)),
    )
    priorities = (
        re.compile(r"^executive summary$"),
        re.compile(r"^summary$"),
        re.compile(r"^scope of report$"),
        re.compile(r"^scope of the report$"),
        re.compile(r"^scope of this report$"),
        re.compile(r"^overview$"),
        re.compile(r"^introduction$"),
    )
    ranked: list[tuple[int, int, int]] = []
    for index, block in enumerate(ordered):
        level = _heading_level(str(block.get("label", "")))
        if level is None:
            continue
        heading = _summary_heading(str(block.get("text", "")))
        for priority, pattern in enumerate(priorities):
            if pattern.fullmatch(heading):
                ranked.append((priority, index, level))
                break

    for _, index, source_level in sorted(ranked):
        candidates: list[str] = []
        for block in ordered[index + 1 :]:
            label = str(block.get("label", ""))
            level = _heading_level(label)
            if level is not None and level <= source_level:
                break
            if label in {"header", "footer", "title", "document_index"}:
                continue
            text = str(block.get("text", "")).strip()
            if label == "text" and len(text) >= 45:
                candidates.append(text)
            for item in block.get("list_items") or []:
                item_text = re.sub(r"^\d+(?:\.\d+)+\s+", "", str(item)).strip()
                if len(item_text) >= 45:
                    candidates.append(item_text)
        if candidates:
            return _summary_from_values(candidates, max_chars)

    fallback = [
        str(block.get("text", "")).strip()
        for block in ordered
        if block.get("label") == "text"
        and len(str(block.get("text", "")).strip()) >= 80
    ]
    if fallback:
        return _summary_from_values(fallback[:3], max_chars)
    return f"This publication presents the reviewed content of {source_name}."


def _format_published_date(value: Any) -> str:
    raw = str(value or "").strip().rstrip(".")
    if not raw:
        return "date not specified"
    normalized = re.sub(
        r"^published\s+(?:on\s+)?",
        "",
        re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE),
        flags=re.IGNORECASE,
    ).strip()
    try:
        parsed_iso = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return f"{parsed_iso.strftime('%B')} {parsed_iso.day}, {parsed_iso.year}"
    except ValueError:
        pass
    for pattern in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
    ):
        try:
            parsed = datetime.strptime(normalized, pattern)
            return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"
        except ValueError:
            continue
    return raw


def _reader_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        section
        for section in sections
        if section.get("id") != "front-matter"
        and str(section.get("displayTitle", "")).strip().casefold()
        not in {"front matter", "contents", "table of contents"}
    ]


def _ordered_reader_sections(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep H1s in printed-contents order and place missing entries by page.

    Most resolved H1s carry a printed-TOC sequence.  Designed front/back matter
    can occasionally lack that field, so a plain ``None -> end`` sort would
    move Preface to the back or detach Appendices from its physical position.
    Missing entries are interpolated between the nearest sequenced page anchors.
    """

    if not sections:
        return []
    original_positions = {id(section): index for index, section in enumerate(sections)}
    anchors = sorted(
        (
            int(section.get("page", 0)),
            float(section["tocSequence"]),
            original_positions[id(section)],
        )
        for section in sections
        if isinstance(section.get("tocSequence"), int)
    )
    if not anchors:
        return list(sections)

    def estimated_sequence(section: dict[str, Any]) -> float:
        sequence = section.get("tocSequence")
        if isinstance(sequence, int):
            return float(sequence)
        page = int(section.get("page", 0))
        before = [anchor for anchor in anchors if anchor[0] <= page]
        after = [anchor for anchor in anchors if anchor[0] > page]
        if not before:
            first_page, first_sequence, _ = anchors[0]
            return first_sequence - 1 - max(0, first_page - page) / 100_000
        if not after:
            last_page, last_sequence, _ = anchors[-1]
            return last_sequence + 1 + max(0, page - last_page) / 100_000
        previous_page, previous_sequence, _ = before[-1]
        next_page, next_sequence, _ = after[0]
        span = max(1, next_page - previous_page)
        fraction = (page - previous_page) / span
        if next_sequence > previous_sequence:
            return previous_sequence + fraction * (
                next_sequence - previous_sequence
            )
        return previous_sequence + 0.5 + fraction / 100

    return sorted(
        sections,
        key=lambda section: (
            estimated_sequence(section),
            int(section.get("page", 0)),
            original_positions[id(section)],
        ),
    )


def _list_publication_blocks(
    block: dict[str, Any],
    page: int,
) -> list[dict[str, Any]]:
    """Preserve ordered markers and numbered paragraphs from Docling lists."""
    entries = block.get("list_entries")
    if not entries:
        source_lines = str(block.get("text", "")).splitlines()
        if not source_lines:
            source_lines = [str(value) for value in block.get("list_items") or []]
        entries = [
            entry
            for value in source_lines
            if (entry := _parsed_list_entry(value)) is not None
        ]
    output: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    pending_style: str | None = None
    pending_start: int | None = None

    def flush() -> None:
        nonlocal pending_style, pending_start
        if not pending:
            return
        output.append(
            {
                "type": "list",
                "style": pending_style or "unordered",
                "items": list(pending),
                "start": pending_start,
                "page": page,
            }
        )
        pending.clear()
        pending_style = None
        pending_start = None

    for entry in entries:
        parsed_text = _parsed_list_entry(str(entry.get("text", "")))
        marker = str(entry.get("marker", "")).strip()
        if marker:
            text = str(entry.get("text", "")).strip()
        elif parsed_text:
            marker = str(parsed_text.get("marker", ""))
            text = str(parsed_text.get("text", ""))
        else:
            text = str(entry.get("text", "")).strip()
        enumerated = bool(entry.get("enumerated")) or bool(
            re.fullmatch(
                r"\((?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\)|"
                r"(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)]",
                marker,
            )
        )
        marker_number = re.fullmatch(r"\(?(\d+)[.)]", marker)
        marker_value = int(marker_number.group(1)) if marker_number else None
        numbered_paragraph = re.match(r"^(\d+(?:\.\d+)+)\s+(.+)$", text, re.DOTALL)
        if numbered_paragraph and not marker:
            flush()
            output.append(
                {
                    "type": "paragraph",
                    "text": numbered_paragraph.group(2),
                    "number": numbered_paragraph.group(1),
                    "page": page,
                }
            )
            continue
        style = "ordered" if enumerated else "unordered"
        level = max(0, int(entry.get("level", 0) or 0))
        if pending and level == 0 and pending_style != style:
            flush()
        if pending_style is None:
            pending_style = style
        if style == "ordered" and pending_start is None:
            pending_start = marker_value or 1
        if text:
            pending.append(
                {
                    "text": text,
                    "marker": marker,
                    "level": level,
                    "ordered": enumerated,
                    "value": marker_value,
                }
            )
    flush()
    return output


def _table_publication_block(
    block: dict[str, Any],
    page: int,
    counts: Counter[str],
) -> dict[str, Any]:
    table = block.get("table_data") or {
        "headers": ["Column 1"],
        "rows": [[str(block.get("text", ""))]],
    }
    rows: list[list[dict[str, Any]]] = []
    headers = list(table.get("headers", []))
    if headers:
        rows.append(
            [
                {
                    "text": str(value),
                    "rowSpan": 1,
                    "colSpan": 1,
                    "columnHeader": True,
                    "rowHeader": False,
                    "startColumn": index,
                }
                for index, value in enumerate(headers)
            ]
        )
    rows.extend(
        [
            [
                {
                    "text": str(value),
                    "rowSpan": 1,
                    "colSpan": 1,
                    "columnHeader": False,
                    "rowHeader": False,
                    "startColumn": index,
                }
                for index, value in enumerate(row)
            ]
            for row in table.get("rows", [])
        ]
    )
    return {
        "type": "table",
        "id": _unique_slug(f"table-{str(block.get('id', ''))}", counts),
        "caption": str(table.get("caption") or block.get("caption") or "").strip(),
        "rows": rows,
        "page": page,
    }


def _box_section_publication_content(
    block: dict[str, Any],
    page: int,
    counts: Counter[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    children = block.get("box_section_blocks") or block.get("callout_blocks") or []
    if not children:
        text = str(block.get("text", ""))
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) > 1 and any(
            _ORDERED_LIST_MARKER.match(line.strip())
            or _BULLET_LIST_MARKER.match(line.strip())
            for line in lines
        ):
            return _list_publication_blocks(
                {"text": text, "list_entries": []}, page
            )
        return [
            {"type": "paragraph", "text": value.strip(), "page": page}
            for value in re.split(r"\n\s*\n", text)
            if value.strip()
        ]
    for child in children:
        label = str(child.get("label", "text"))
        child_page = int(child.get("page", page))
        text = str(child.get("text", "")).strip()
        if label in {"list", "list_item"}:
            output.extend(_list_publication_blocks(child, child_page))
        elif label == "table":
            output.append(_table_publication_block(child, child_page, counts))
        elif label == "picture":
            output.append(
                {
                    "type": "figure",
                    "id": _unique_slug(
                        f"figure-{str(child.get('id', ''))}", counts
                    ),
                    "caption": text or "Figure",
                    "page": child_page,
                    "sourceBlockId": str(child.get("id", "")),
                }
            )
        elif label == "footnote":
            output.append(
                {
                    "type": "footnote",
                    "id": _unique_slug(
                        f"box-footnote-{str(child.get('id', ''))}", counts
                    ),
                    "text": text,
                    "page": child_page,
                }
            )
        elif label.startswith("section_header_"):
            level = min(5, max(1, int(label.rsplit("_", 1)[1])))
            output.append(
                {
                    "type": "heading",
                    "id": _unique_slug(text, counts),
                    "text": text,
                    "level": level,
                    "page": child_page,
                }
            )
        elif label == "formula":
            output.append({"type": "formula", "text": text, "page": child_page})
        elif label == "caption":
            output.append({"type": "caption", "text": text, "page": child_page})
        elif label == "form":
            output.append(
                {
                    "type": "group",
                    "label": "Form fields",
                    "items": [{"text": value} for value in _split_lines(text)],
                    "page": child_page,
                }
            )
        elif text:
            numbered = re.match(r"^(\d+(?:\.\d+)+)\s+(.+)$", text, re.DOTALL)
            output.append(
                {
                    "type": "paragraph",
                    "text": numbered.group(2) if numbered else text,
                    "number": numbered.group(1) if numbered else None,
                    "page": child_page,
                }
            )
    return output


def build_publication(
    blocks: list[dict[str, Any]],
    record: dict[str, Any],
    summary_max_chars: int = 600,
) -> dict[str, Any]:
    blocks = [block for block in blocks if not block.get("removed")]
    counts: Counter[str] = Counter()
    sections: list[dict[str, Any]] = []
    title_blocks = [
        block for block in blocks if block.get("label") == "title" and block.get("text")
    ]
    source_name = (
        str(title_blocks[0]["text"])
        if title_blocks
        else str(record.get("title", "Document"))
    )

    current: dict[str, Any] = {
        "id": "front-matter",
        "title": "Front matter",
        "displayTitle": "Front matter",
        "tocSequence": None,
        "page": 1,
        "blocks": [],
        "headings": [],
        "footnotes": [],
    }
    def finish_current() -> None:
        if (
            current["id"] != "front-matter"
            or current["blocks"]
            or current["footnotes"]
        ):
            if current["id"] != "front-matter":
                first_heading_index = next(
                    (
                        index
                        for index, block in enumerate(current["blocks"])
                        if block.get("type") == "heading"
                    ),
                    -1,
                )
                if first_heading_index >= 0:
                    first_heading = current["blocks"][first_heading_index]
                    if _section_key(str(first_heading.get("text", ""))) == _section_key(
                        str(current["title"])
                    ):
                        current["displayTitle"] = str(
                            first_heading.get("text") or current["displayTitle"]
                        )
                        current["blocks"].pop(first_heading_index)
            previous_level = 1
            for content_block in current["blocks"]:
                if content_block.get("type") != "heading":
                    continue
                requested_level = min(
                    5, max(2, int(content_block.get("level", 2)))
                )
                # Accessible HTML must never skip a heading rank.  Typography
                # and numbering still choose the intended tier, but a missing
                # intermediate source heading is closed up for a valid H1–H5
                # outline.
                content_block["level"] = min(
                    requested_level, previous_level + 1
                )
                previous_level = int(content_block["level"])
            current["headings"] = [
                block for block in current["blocks"] if block.get("type") == "heading"
            ]
            sections.append(current.copy())

    for block in sorted(blocks, key=lambda value: int(value.get("order", 0))):
        label = str(block.get("label", "unspecified"))
        text = str(block.get("text", "")).strip()
        page = int(block.get("page", 1))

        if label == "title" or label in {"header", "footer"}:
            continue

        starts_section = label == "section_header_1"
        if starts_section:
            if current["id"] != "front-matter" and _section_key(text) == _section_key(
                str(current["title"])
            ):
                current["displayTitle"] = text or current["displayTitle"]
                current["page"] = min(page, int(current.get("page", page)))
                continue
            finish_current()
            current = {
                "id": _unique_slug(text or f"section-{len(sections) + 1}", counts),
                "title": text or f"Section {len(sections) + 1}",
                "displayTitle": text or f"Section {len(sections) + 1}",
                "isChapter": _is_chapter_title(text),
                "tocSequence": block.get("toc_sequence"),
                "page": page,
                "blocks": [],
                "headings": [],
                "footnotes": [],
            }
            continue

        if label == "footnote":
            current["footnotes"].append(
                {
                    "id": _unique_slug(
                        f"footnote-{len(current['footnotes']) + 1}", counts
                    ),
                    "text": text,
                    "page": page,
                }
            )
            continue

        if label.startswith("section_header_"):
            level = min(5, max(1, int(label.rsplit("_", 1)[1])))
            heading = {
                "type": "heading",
                "id": _unique_slug(text, counts),
                "text": text,
                "level": level,
                "page": page,
                "tocSequence": block.get("toc_sequence"),
            }
            current["blocks"].append(heading)
            continue

        if label == "document_index":
            continue

        if label == "table":
            current["blocks"].append(_table_publication_block(block, page, counts))
            continue

        if label in {"box_section", "callout"}:
            current["blocks"].append(
                {
                    "type": "box_section",
                    "id": _unique_slug(
                        f"box-section-{block.get('box_section_title') or block.get('callout_title') or len(current['blocks']) + 1}",
                        counts,
                    ),
                    "title": str(
                        block.get("box_section_title")
                        or block.get("callout_title")
                        or "Box Section"
                    ),
                    "variant": str(
                        block.get("box_section_kind")
                        or block.get("callout_kind")
                        or "information"
                    ),
                    "blocks": _box_section_publication_content(block, page, counts),
                    "page": page,
                }
            )
            continue

        if label in {"list", "list_item"}:
            current["blocks"].extend(_list_publication_blocks(block, page))
            continue

        if label == "picture":
            current["blocks"].append(
                {
                    "type": "figure",
                    "id": _unique_slug(f"figure-{len(current['blocks']) + 1}", counts),
                    "caption": text or "Figure",
                    "page": page,
                    "sourceBlockId": str(block.get("id", "")),
                }
            )
            continue

        if label == "caption":
            current["blocks"].append({"type": "caption", "text": text, "page": page})
            continue

        if label == "form":
            current["blocks"].append(
                {
                    "type": "group",
                    "label": "Form fields",
                    "items": [{"text": value} for value in _split_lines(text)],
                    "page": page,
                }
            )
            continue

        if label == "formula":
            current["blocks"].append(
                {
                    "type": "formula",
                    "text": text,
                    "page": page,
                }
            )
            continue

        numbered = re.match(r"^(\d+(?:\.\d+)+)\s+(.+)$", text, re.DOTALL)
        current["blocks"].append(
            {
                "type": "paragraph",
                "text": numbered.group(2) if numbered else text,
                "number": numbered.group(1) if numbered else None,
                "page": page,
            }
        )

    finish_current()
    reader_sections = _ordered_reader_sections(_reader_sections(sections))
    if not reader_sections:
        fallback = next(
            (
                section
                for section in sections
                if section.get("blocks") or section.get("footnotes")
            ),
            None,
        )
        if fallback:
            reader_sections = [
                {
                    **fallback,
                    "id": "document-body",
                    "title": "Document",
                    "displayTitle": "Document",
                }
            ]

    stats = {
        "pages": int(record.get("pages", 0)),
        "textItems": sum(
            1
            for block in blocks
            if block.get("label")
            in {
                "text",
                "title",
                "caption",
                "footnote",
                "formula",
                "box_section",
                "callout",
                "section_header_1",
                "section_header_2",
                "section_header_3",
                "section_header_4",
                "section_header_5",
            }
        ),
        "tables": sum(
            1 for block in blocks if block.get("label") in {"table", "document_index"}
        ),
        "pictures": sum(1 for block in blocks if block.get("label") == "picture"),
        "footnotes": sum(1 for block in blocks if block.get("label") == "footnote"),
    }
    return {
        "schemaName": "Konverter accessible document",
        "schemaVersion": "1.0",
        "sourceName": source_name,
        "sourceFile": str(record.get("file_name", "source.pdf")),
        "summary": [_publication_summary(blocks, source_name, summary_max_chars)],
        "sections": reader_sections,
        "stats": stats,
    }


def _iso_published_date(value: Any) -> str | None:
    """Normalise the reviewed date to ISO 8601 (YYYY[-MM[-DD]]) when possible."""
    raw = re.sub(
        r"^published\s+(?:on\s+)?",
        "",
        str(value or "").strip().rstrip("."),
        flags=re.IGNORECASE,
    )
    raw = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE).strip()
    if not raw:
        return None
    if re.fullmatch(
        r"(?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?", raw
    ):
        return raw
    for pattern, formatter in (
        ("%Y-%m-%d", "%Y-%m-%d"),
        ("%Y/%m/%d", "%Y-%m-%d"),
        ("%d/%m/%Y", "%Y-%m-%d"),
        ("%d-%m-%Y", "%Y-%m-%d"),
        ("%d.%m.%Y", "%Y-%m-%d"),
        ("%d %B %Y", "%Y-%m-%d"),
        ("%d %b %Y", "%Y-%m-%d"),
        ("%B %d, %Y", "%Y-%m-%d"),
        ("%B %d %Y", "%Y-%m-%d"),
        ("%b %d, %Y", "%Y-%m-%d"),
        ("%B %Y", "%Y-%m"),
        ("%b %Y", "%Y-%m"),
    ):
        try:
            return datetime.strptime(raw, pattern).strftime(formatter)
        except ValueError:
            continue
    return None


def _split_values(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


ISBN_PATTERN = re.compile(
    r"\bISBNs?\b[:\s]*([0-9][0-9\- ]{7,20}[0-9Xx])", re.IGNORECASE
)
ISSN_PATTERN = re.compile(r"\bISSN\b[:\s]*([0-9]{4}-?[0-9]{3}[0-9Xx])", re.IGNORECASE)
SERIES_PATTERN = re.compile(r"^Series:\s*(.+)$", re.IGNORECASE)


def _citation_entry(value: str) -> Any:
    """Type legislation and case citations so downstream AI can use them."""
    if re.search(r"\bAct\s+(?:19|20)\d{2}\b", value):
        return {"@type": "Legislation", "name": value}
    if re.search(r"\b\S+\s+v\s+\S+", value):
        return {"@type": "CreativeWork", "name": value}
    return value


def _prune(node: dict[str, Any]) -> dict[str, Any]:
    """Omit properties whose values are unknown rather than guessing."""
    return {
        key: value for key, value in node.items() if value not in (None, "", [], {})
    }


def _accessibility_properties(publication: dict[str, Any]) -> dict[str, Any]:
    """Claim only the accessibility the generated HTML actually provides.

    The exported page always contains images (cover, logo) with alt text and
    offers structural navigation, so those claims are constant. Text
    sufficiency and the alternativeText claim depend on every figure in this
    particular document carrying a caption (which becomes its alt text).
    """
    def figures_in(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        figures: list[dict[str, Any]] = []
        for block in blocks:
            if block.get("type") == "figure":
                figures.append(block)
            children = block.get("blocks")
            if isinstance(children, list):
                figures.extend(figures_in(children))
        return figures

    figures = [
        figure
        for section in publication.get("sections", [])
        for figure in figures_in(section.get("blocks", []))
    ]
    all_figures_captioned = all(str(f.get("caption", "")).strip() for f in figures)
    features = ["structuralNavigation", "tableOfContents", "readingOrder"]
    if all_figures_captioned:
        features.append("alternativeText")
    summary = (
        "This HTML edition provides structural navigation, a table of contents, "
        "a defined reading order and alternative text for figures."
        if all_figures_captioned
        else "This HTML edition provides structural navigation, a table of contents "
        "and a defined reading order. Some figures may not include source-supplied "
        "alternative text."
    )
    return {
        "accessMode": ["textual", "visual"],
        "accessModeSufficient": [{"@type": "ItemList", "itemListElement": ["textual"]}]
        if all_figures_captioned
        else None,
        "accessibilityFeature": features,
        "accessibilityHazard": [
            "noFlashingHazard",
            "noMotionSimulationHazard",
            "noSoundHazard",
        ],
        "accessibilitySummary": summary,
    }


def build_json_ld(
    document_id: str,
    publication: dict[str, Any],
    metadata: dict[str, Any],
    *,
    site_url: str = "",
    site_name: str = "",
    page_url_template: str = "",
    public_api_url: str = "",
    license_url: str = "",
    copyright_holder: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Schema.org graph combining document metadata with page/site context.

    Generation rules:
    - Node ids are page-specific: with KONVERTER_PAGE_URL_TEMPLATE configured
      the WebPage/breadcrumb ids are absolute URLs; otherwise they are
      document-scoped fragments that resolve against the hosting URL.
    - The WebSite describes the hosting site (KONVERTER_SITE_URL/_NAME). The
      document's publisher is linked as site owner only when the configured
      site name matches the publisher; hosting elsewhere leaves them separate.
    - The report's own datePublished stays distinct from the generated page's
      datePublished/dateModified (the approval timestamp).
    - author is only emitted when the source identifies one (the current
      metadata schema has no author field, so it is omitted).
    - citation carries only the human-confirmed citation list; ISBN/ISSN move
      to identifier and a series statement becomes isPartOf/reportNumber.
    - Unknown values are omitted, never guessed.
    """
    publishers = _split_values(metadata.get("publisher"))
    jurisdictions = _split_values(metadata.get("jurisdiction"))
    authors = _split_values(metadata.get("authors"))
    raw_date = str(metadata.get("published_date") or "").strip()
    title = str(metadata.get("title") or publication.get("sourceName") or "").strip()
    report_id = f"urn:uuid:{document_id}"
    api_root = (
        f"{public_api_url.rstrip('/')}/api/documents/{document_id}"
        if public_api_url
        else f"/api/documents/{document_id}"
    )
    html_url = f"{api_root}/exports/accessible.html"
    source_url = f"{api_root}/source"
    cover_url = f"{api_root}/cover"

    page_url = ""
    if page_url_template:
        page_url = page_url_template.replace(
            "{slug}", _slug(title) or document_id
        ).replace("{id}", document_id)
    page_id = page_url or f"#webpage-{document_id}"
    breadcrumb_id = (
        f"{page_url}#breadcrumb" if page_url else f"#breadcrumb-{document_id}"
    )
    image_id = (
        f"{page_url}#primaryimage"
        if page_url
        else f"#primaryimage-{document_id}"
    )

    citations: list[Any] = []
    identifiers: list[dict[str, Any]] = []
    series_name: str | None = None
    report_number: str | None = None
    for value in _split_values(metadata.get("citations")):
        isbn = ISBN_PATTERN.search(value)
        issn = ISSN_PATTERN.search(value)
        series = SERIES_PATTERN.match(value)
        if isbn:
            identifiers.append(
                {
                    "@type": "PropertyValue",
                    "propertyID": "ISBN",
                    "value": isbn.group(1).strip(),
                }
            )
        elif issn:
            identifiers.append(
                {
                    "@type": "PropertyValue",
                    "propertyID": "ISSN",
                    "value": issn.group(1).strip(),
                }
            )
        elif series:
            statement = series.group(1).strip()
            numbered = re.fullmatch(r"(.+?)[\s,]+(?:no\.?\s*)?(\d+)", statement)
            if numbered:
                series_name, report_number = (
                    numbered.group(1).strip(),
                    numbered.group(2),
                )
            else:
                series_name = statement
        else:
            citations.append(_citation_entry(value))

    site_is_owner = bool(
        site_url
        and site_name
        and publishers
        and site_name.strip().lower() == publishers[0].strip().lower()
    )
    organisation_nodes = [
        _prune(
            {
                "@type": "Organization",
                "@id": (
                    f"{site_url}/#organization"
                    if site_is_owner and index == 0
                    else f"#organization-{document_id}"
                    + ("" if index == 0 else f"-{index + 1}")
                ),
                "name": value,
                "url": f"{site_url}/" if site_is_owner and index == 0 else None,
            }
        )
        for index, value in enumerate(publishers)
    ]
    organisation_refs = [{"@id": node["@id"]} for node in organisation_nodes]
    holder_ref: dict[str, str] | None = None
    if copyright_holder:
        matching_holder = next(
            (
                node
                for node in organisation_nodes
                if str(node.get("name", "")).strip().casefold()
                == copyright_holder.strip().casefold()
            ),
            None,
        )
        if matching_holder is not None:
            holder_ref = {"@id": str(matching_holder["@id"])}
        else:
            holder_node = {
                "@type": "Organization",
                "@id": f"#copyright-holder-{document_id}",
                "name": copyright_holder,
            }
            organisation_nodes.append(holder_node)
            holder_ref = {"@id": holder_node["@id"]}

    description = " ".join(
        str(value).strip()
        for value in publication.get("summary", [])
        if str(value).strip()
    )
    language = (
        "en-AU"
        if any("australia" in value.lower() for value in jurisdictions)
        else "en"
    )

    report = _prune(
        {
            "@type": "Report",
            "@id": report_id,
            "name": title,
            "description": description or None,
            "inLanguage": language,
            # Only present when the source metadata identifies authors.
            "author": [{"@type": "Person", "name": value} for value in authors],
            "publisher": organisation_refs,
            "datePublished": _iso_published_date(raw_date) or raw_date or None,
            "license": license_url or None,
            "copyrightHolder": holder_ref,
            "reportNumber": report_number,
            "isPartOf": {"@type": "CreativeWorkSeries", "name": series_name}
            if series_name
            else None,
            "identifier": identifiers,
            "spatialCoverage": [
                {"@type": "AdministrativeArea", "name": value}
                for value in jurisdictions
            ],
            "citation": citations,
            "isAccessibleForFree": True,
            **_accessibility_properties(publication),
            "encoding": [
                {
                    "@type": "MediaObject",
                    "encodingFormat": "application/pdf",
                    "contentUrl": source_url,
                },
                {
                    "@type": "MediaObject",
                    "encodingFormat": "text/html",
                    "contentUrl": html_url,
                },
            ],
            "image": {"@id": image_id},
            "mainEntityOfPage": {"@id": page_id},
            "hasPart": [
                _prune(
                    {
                    "@type": "Chapter",
                    "@id": f"{report_id}#{section['id']}",
                    "isPartOf": {"@id": report_id},
                    "name": section["displayTitle"],
                    "position": index + 1,
                    "url": f"{page_url}#{section['id']}" if page_url else None,
                    }
                )
                for index, section in enumerate(publication.get("sections", []))
            ],
        }
    )

    web_page = _prune(
        {
            "@type": "WebPage",
            "@id": page_id,
            "url": page_url or None,
            "name": f"{title} - {site_name}" if site_name else title,
            "mainEntity": {"@id": report_id},
            "isPartOf": {"@id": f"{site_url}/#website"} if site_url else None,
            "breadcrumb": {"@id": breadcrumb_id} if site_url else None,
            "inLanguage": language,
            "datePublished": generated_at,
            "dateModified": generated_at,
            "primaryImageOfPage": {"@id": image_id},
            "potentialAction": [
                {"@type": "ReadAction", "target": [page_url or html_url]}
            ],
        }
    )

    image_node = {
        "@type": "ImageObject",
        "@id": image_id,
        "url": cover_url,
        "contentUrl": cover_url,
        "encodingFormat": "image/png",
        "caption": f"Cover of {title}",
        "representativeOfPage": True,
    }
    graph: list[dict[str, Any]] = [
        report,
        web_page,
        image_node,
        *organisation_nodes,
    ]
    if site_url:
        graph.append(
            _prune(
                {
                    "@type": "WebSite",
                    "@id": f"{site_url}/#website",
                    "url": f"{site_url}/",
                    "name": site_name or None,
                    "publisher": organisation_refs[:1] if site_is_owner else None,
                    "inLanguage": language,
                }
            )
        )
        graph.append(
            {
                "@type": "BreadcrumbList",
                "@id": breadcrumb_id,
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "Home",
                        "item": f"{site_url}/",
                    },
                    {"@type": "ListItem", "position": 2, "name": title},
                ],
            }
        )

    return {"@context": "https://schema.org", "@graph": graph}


def _data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _render_table_cell(cell: dict[str, Any]) -> str:
    tag = "th" if cell.get("columnHeader") or cell.get("rowHeader") else "td"
    scope = (
        ' scope="col"'
        if cell.get("columnHeader")
        else ' scope="row"'
        if cell.get("rowHeader")
        else ""
    )
    return f"<{tag}{scope}>{html.escape(str(cell.get('text', '')))}</{tag}>"


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
        list_items = ""
        for item in group:
            value_attribute = (
                f' value="{int(item["value"])}"'
                if ordered and item.get("value") is not None
                else ""
            )
            list_items += (
                f"<li{value_attribute}>{html.escape(str(item.get('text', '')))}"
                f"{_render_list_items(item.get('children', []))}</li>"
            )
        output.append(
            f'<{tag} class="source-list"{start_attribute}>{list_items}</{tag}>'
        )
    return "".join(output)


def _render_block(
    block: dict[str, Any],
    figure_directory: Path | None = None,
) -> str:
    block_type = block.get("type")
    if block_type == "heading":
        level = min(6, max(2, int(block.get("level", 2))))
        return f'<h{level} id="{html.escape(str(block["id"]))}">{html.escape(str(block["text"]))}</h{level}>'
    if block_type == "paragraph":
        text = html.escape(str(block.get("text", "")))
        number = block.get("number")
        if number:
            safe_number = html.escape(str(number))
            return (
                f'<div class="numbered-paragraph"><span aria-hidden="true">{safe_number}</span>'
                f'<p><span class="sr-only">Paragraph {safe_number}. </span>{text}</p></div>'
            )
        return f"<p>{text}</p>"
    if block_type == "list":
        if block.get("style") == "numbered-paragraphs":
            return "".join(
                (
                    f'<div class="numbered-paragraph"><span aria-hidden="true">'
                    f"{html.escape(str(item.get('marker', '')))}</span><p>"
                    f'<span class="sr-only">Paragraph {html.escape(str(item.get("marker", "")))}. </span>'
                    f"{html.escape(str(item.get('text', '')))}</p></div>"
                )
                for item in block.get("items", [])
            )
        ordered = block.get("style") == "ordered"
        raw_start = block.get("start", 1)
        try:
            start_value = max(1, int(raw_start if raw_start is not None else 1))
        except (TypeError, ValueError):
            start_value = 1
        tree = _nested_list_tree(
            [dict(item) for item in block.get("items", [])],
            ordered,
        )
        return _render_list_items(tree, start_value)
    if block_type in {"box_section", "callout"}:
        box_id = html.escape(str(block.get("id", "box-section")))
        title = html.escape(str(block.get("title", "Box Section")))
        variant = re.sub(
            r"[^a-z-]",
            "",
            str(block.get("variant", "information")).lower(),
        ) or "information"
        content = "".join(
            _render_block(child, figure_directory)
            for child in block.get("blocks", [])
        )
        return (
            f'<section class="document-box-section document-box-section--{variant}" '
            f'aria-labelledby="{box_id}-title">'
            f'<h3 id="{box_id}-title">{title}</h3>'
            f'<div class="document-box-section-content">{content}</div></section>'
        )
    if block_type == "table":
        raw_caption = str(block.get("caption", "")).strip()
        caption = html.escape(raw_caption)
        rows = block.get("rows", [])
        header_rows = [
            row for row in rows if row and all(cell.get("columnHeader") for cell in row)
        ][:1]
        body_rows = [row for row in rows if row not in header_rows]
        head_html = (
            "<thead>"
            + "".join(
                f"<tr>{''.join(_render_table_cell(cell) for cell in row)}</tr>"
                for row in header_rows
            )
            + "</thead>"
            if header_rows
            else ""
        )
        body_html = "".join(
            f"<tr>{''.join(_render_table_cell(cell) for cell in row)}</tr>"
            for row in body_rows
        )
        caption_html = f"<caption>{caption}</caption>" if caption else ""
        aria_label = caption or "Table"
        return (
            f'<div class="table-scroll" tabindex="0" role="region" aria-label="{aria_label}; scroll horizontally when needed">'
            f'<table id="{html.escape(str(block.get("id", "")))}">{caption_html}{head_html}<tbody>{body_html}</tbody></table></div>'
        )
    if block_type == "footnote":
        return (
            f'<p class="document-footnote" role="doc-footnote" '
            f'id="{html.escape(str(block.get("id", "")))}">'
            f'{html.escape(str(block.get("text", "")))}</p>'
        )
    if block_type == "figure":
        caption = html.escape(str(block.get("caption", "Figure")))
        image_key = str(block.get("imageKey", ""))
        image_path = (
            figure_directory / f"figure-{image_key}.png"
            if figure_directory is not None and image_key
            else None
        )
        image_uri = _data_uri(image_path) if image_path is not None else ""
        visual = (
            f'<img class="document-figure-image" src="{image_uri}" alt="{caption}">'
            if image_uri
            else f'<div class="figure-unavailable" role="img" aria-label="{caption}">'
            "The original figure image is unavailable.</div>"
        )
        return (
            f'<figure id="{html.escape(str(block.get("id", "")))}">'
            f"{visual}"
            f"<figcaption>{caption}</figcaption></figure>"
        )
    if block_type == "caption":
        return f'<p class="caption">{html.escape(str(block.get("text", "")))}</p>'
    if block_type == "formula":
        formula = html.escape(str(block.get("text", "")))
        return f'<div class="document-formula" role="math" aria-label="Formula">{formula}</div>'
    if block_type == "group":
        legend = html.escape(str(block.get("label", "Document details")))
        items = "".join(
            f"<p>{html.escape(str(item.get('text', '')))}</p>"
            for item in block.get("items", [])
        )
        return f"<fieldset><legend>{legend}</legend>{items}</fieldset>"
    return ""


def build_accessible_html(
    document_id: str,
    publication: dict[str, Any],
    metadata: dict[str, Any],
    json_ld: dict[str, Any],
    cover_path: Path,
    logo_path: Path,
    figure_directory: Path | None = None,
) -> str:
    sections = publication.get("sections", [])

    def render_footnotes(section: dict[str, Any]) -> str:
        footnotes = section.get("footnotes", [])
        if not footnotes:
            return ""
        section_id = html.escape(str(section["id"]))
        return (
            f'<section class="reader-footnotes" aria-labelledby="footnotes-{section_id}">'
            f'<h2 id="footnotes-{section_id}">References and footnotes</h2><ol>'
            + "".join(
                f'<li id="{html.escape(str(note["id"]))}">{html.escape(str(note["text"]))}</li>'
                for note in footnotes
            )
            + "</ol></section>"
        )

    def render_contents_list(
        list_class: str,
        current_section_id: str | None = None,
    ) -> str:
        items: list[str] = []
        for section in sections:
            section_id = html.escape(str(section["id"]))
            section_title = html.escape(str(section["displayTitle"]))
            is_current = str(section["id"]) == current_section_id
            current_class = " is-active" if is_current else ""
            current_attribute = ' aria-current="page"' if is_current else ""
            major_headings = [
                heading
                for heading in section.get("headings", [])
                if int(heading.get("level", 2)) == 2
            ]
            major_headings.sort(
                key=lambda heading: (
                    int(heading["tocSequence"])
                    if isinstance(heading.get("tocSequence"), int)
                    else 1_000_000,
                    int(heading.get("page", 0)),
                )
            )
            child_items = "".join(
                f'<li class="toc-h3"><a href="#reader-{section_id}" '
                f'data-open-section="{section_id}" '
                f'data-heading="{html.escape(str(heading["id"]))}">'
                f'{html.escape(str(heading["text"]))}</a></li>'
                for heading in major_headings
            )
            child_list = f"<ul>{child_items}</ul>" if child_items else ""
            items.append(
                f'<li class="toc-h2{current_class}"><a href="#reader-{section_id}" '
                f'data-open-section="{section_id}"{current_attribute}>'
                f"{section_title}</a>{child_list}</li>"
            )
        return f'<ul class="{html.escape(list_class)}">{"".join(items)}</ul>'

    def render_landing_contents() -> str:
        items: list[str] = []
        for section in sections:
            section_id = html.escape(str(section["id"]))
            section_title = html.escape(str(section["displayTitle"]))
            major_headings = [
                heading
                for heading in section.get("headings", [])
                if int(heading.get("level", 2)) == 2
            ]
            major_headings.sort(
                key=lambda heading: (
                    int(heading["tocSequence"])
                    if isinstance(heading.get("tocSequence"), int)
                    else 1_000_000,
                    int(heading.get("page", 0)),
                )
            )
            if not major_headings:
                items.append(
                    '<div class="publication-contents-item publication-contents-direct toc-h2">'
                    f'<a href="#reader-{section_id}" data-open-section="{section_id}">'
                    f"<span>{section_title}</span></a></div>"
                )
                continue

            child_items = (
                f'<li class="read-full"><a href="#reader-{section_id}" '
                f'data-open-section="{section_id}">Read full section</a></li>'
                + "".join(
                    f'<li class="toc-h3"><a href="#reader-{section_id}" '
                    f'data-open-section="{section_id}" '
                    f'data-heading="{html.escape(str(heading["id"]))}">'
                    f'{html.escape(str(heading["text"]))}</a></li>'
                    for heading in major_headings
                )
            )
            items.append(
                '<details class="publication-contents-item toc-h2">'
                f'<summary><span>{section_title}</span>'
                '<span class="publication-contents-chevron" aria-hidden="true"></span>'
                '</summary>'
                f'<div class="publication-contents-submenu"><ul>{child_items}</ul></div>'
                '</details>'
            )
        return f'<div class="konverter-page-menu">{"".join(items)}</div>'

    def render_reader(section: dict[str, Any], index: int) -> str:
        section_id = html.escape(str(section["id"]))
        previous_link = (
            f'<a href="#reader-{html.escape(str(sections[index - 1]["id"]))}" '
            f'data-open-section="{html.escape(str(sections[index - 1]["id"]))}"><span>Previous</span>'
            f"{html.escape(str(sections[index - 1]['displayTitle']))}</a>"
            if index > 0
            else '<span class="pagination-disabled"><span>Previous</span>Beginning of document</span>'
        )
        next_link = (
            f'<a href="#reader-{html.escape(str(sections[index + 1]["id"]))}" '
            f'data-open-section="{html.escape(str(sections[index + 1]["id"]))}"><span>Next</span>'
            f"{html.escape(str(sections[index + 1]['displayTitle']))}</a>"
            if index + 1 < len(sections)
            else '<span class="pagination-disabled"><span>Next</span>End of document</span>'
        )
        return (
            f'<section class="vlrc-reader body-content has-sidebar-left" id="reader-{section_id}" '
            f'data-reader="{section_id}" tabindex="-1" aria-labelledby="reader-title-{section_id}">'
            '<div class="inner-body-content">'
            '<aside class="sidebar primary-sidebar" aria-label="Publication contents">'
            '<div class="sidebar-widget-element sidebar-menu-widget publication-page-menu">'
            '<div class="sidebar-title"><h2 class="h2-title-toc">Contents</h2></div>'
            f'<nav class="sidebar-body" aria-label="Publication chapters">'
            f'{render_contents_list("menu", str(section["id"]))}</nav></div></aside>'
            '<div class="main-content"><article class="publication" role="article">'
            '<div class="article-header">'
            f'<a class="publication-parent-link" href="#publication-landing" data-close-reader>{title}</a>'
            f'<h1 class="entry-title single-title" id="reader-title-{section_id}" tabindex="-1">'
            f'{html.escape(str(section["displayTitle"]))}</h1></div>'
            '<section class="entry-content" aria-label="Section content">'
            f'<div class="docling-content-blocks">'
            f'{"".join(_render_block(block, figure_directory) for block in section.get("blocks", []))}'
            f'</div>{render_footnotes(section)}</section>'
            f'<nav class="reader-pagination" aria-label="Document section pagination">'
            f'{previous_link}{next_link}</nav>'
            "</article></div></div></section>"
        )

    raw_title = str(
        metadata.get("title")
        or publication.get("sourceName")
        or "Accessible document"
    )
    title = html.escape(raw_title)
    published_date = html.escape(
        _format_published_date(metadata.get("published_date", ""))
    )
    configured_project_url = str(
        metadata.get("project_url") or metadata.get("projectUrl") or ""
    ).strip()
    if (
        configured_project_url.startswith("/")
        and not configured_project_url.startswith("//")
    ) or re.match(r"^https?://", configured_project_url, re.IGNORECASE):
        project_url = configured_project_url
    else:
        project_url = f"/project/{_project_slug(raw_title)}/"
    project_url = html.escape(project_url, quote=True)
    safe_json_ld = (
        json.dumps(json_ld, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    cover_uri = _data_uri(cover_path)
    summaries = publication.get("summary", [])
    summary_html = "".join(
        f'<p class="vlrc-summary publication-summary">{html.escape(str(value))}</p>'
        for value in summaries
    )
    cover_html = (
        f'<img class="image-link-pub publication-cover" src="{cover_uri}" alt="Cover of {title}">'
        if cover_uri
        else ""
    )
    landing_sections = render_landing_contents()
    reader_sections = "".join(
        render_reader(section, index) for index, section in enumerate(sections)
    )

    return f"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script type="application/ld+json">{safe_json_ld}</script>
<style>
.vlrc-publication-embed,.vlrc-publication-embed *{{box-sizing:border-box}}
.vlrc-publication-embed{{--vlrc-content-gutter:clamp(1rem,2.75vw,3.5rem);width:100%;max-width:none;color:#262626;background:#fff;font-family:Raleway,"Segoe UI",Arial,sans-serif;font-size:16px;line-height:1.65}}
.vlrc-publication-embed a{{color:#064d82;overflow-wrap:anywhere}}
.vlrc-publication-embed a:focus-visible,.vlrc-publication-embed summary:focus-visible,.vlrc-publication-embed [tabindex="-1"]:focus-visible{{outline:3px solid #064d82;outline-offset:3px}}
.vlrc-publication-embed .skip-link{{position:absolute;left:1rem;top:-6rem;z-index:10;padding:.75rem 1rem;background:#fff;color:#064d82;font-weight:700}}
.vlrc-publication-embed .skip-link:focus{{top:1rem}}
.vlrc-publication-embed .vlrc-site-publication{{width:100%;max-width:none;margin:0;padding:2rem var(--vlrc-content-gutter) 3rem}}
.vlrc-publication-embed .article-header{{margin-bottom:1.75rem}}
.vlrc-publication-embed .entry-title{{margin:0 0 1rem;color:#111;font-size:clamp(2rem,4vw,3.15rem);font-weight:700;line-height:1.14}}
.vlrc-publication-embed .no-bullet{{margin:0;padding:0;list-style:none}}
.vlrc-publication-embed .published-date{{color:#4d4d4d;font-size:.94rem}}
.vlrc-publication-embed .published-date span{{font-weight:700}}
.vlrc-publication-embed .main-column-pub{{display:flex;width:100%;align-items:flex-start;justify-content:space-between;gap:clamp(2rem,4vw,5rem);margin:0;flex-wrap:wrap}}
.vlrc-publication-embed .main-content-pub-inner{{min-width:0;flex:1 1 0;max-width:none}}
.vlrc-publication-embed .publication-summary{{max-width:74ch;margin:0 0 1rem}}
.vlrc-publication-embed .publication-contents-heading{{margin:2.5rem 0 1rem;color:#064d82;font-size:1.65rem;line-height:1.25}}
.vlrc-publication-embed .konverter-page-menu{{margin:0;padding:0;border-top:1px solid #9b9b9b}}
.vlrc-publication-embed .publication-contents-item{{margin:0;border:0;border-bottom:1px solid #9b9b9b;background:#fff}}
.vlrc-publication-embed .publication-contents-item>summary,.vlrc-publication-embed .publication-contents-direct>a{{display:flex;min-height:3.15rem;align-items:center;justify-content:space-between;gap:1.25rem;padding:.72rem .8rem;color:#1d1d1d;font-weight:700;line-height:1.35;text-decoration:none}}
.vlrc-publication-embed .publication-contents-item>summary{{cursor:pointer;list-style:none}}
.vlrc-publication-embed .publication-contents-item>summary::-webkit-details-marker{{display:none}}
.vlrc-publication-embed .publication-contents-item>summary:hover,.vlrc-publication-embed .publication-contents-direct>a:hover{{background:#f4f7f9;color:#064d82}}
.vlrc-publication-embed .publication-contents-chevron{{width:.55rem;height:.55rem;flex:0 0 .55rem;margin-right:.25rem;border-right:2px solid #1770a6;border-bottom:2px solid #1770a6;transform:rotate(45deg) translateY(-2px);transform-origin:center;transition:transform .16s ease}}
.vlrc-publication-embed .publication-contents-item[open] .publication-contents-chevron{{transform:rotate(225deg) translate(-1px,-1px)}}
.vlrc-publication-embed .publication-contents-submenu{{border-top:1px solid #e1e1e1;background:#f8fafb}}
.vlrc-publication-embed .publication-contents-submenu ul{{margin:0;padding:0;list-style:none}}
.vlrc-publication-embed .publication-contents-submenu li+li{{border-top:1px solid #e5e5e5}}
.vlrc-publication-embed .publication-contents-submenu a{{display:block;padding:.64rem 1rem .64rem 2rem;color:#333;font-size:.92rem;text-decoration:none}}
.vlrc-publication-embed .publication-contents-submenu .read-full a{{padding-left:1rem;color:#064d82;font-weight:700}}
.vlrc-publication-embed .publication-contents-submenu a:hover,.vlrc-publication-embed .publication-contents-submenu a:focus-visible{{background:#edf3f7;color:#064d82;text-decoration:underline}}
.vlrc-publication-embed .publication-page-menu .menu{{margin:1.25rem 0 0;padding:0;list-style:none}}
.vlrc-publication-embed .publication-page-menu .menu ul{{margin:0;padding:0;list-style:none}}
.vlrc-publication-embed .publication-page-menu .toc-h2>a{{display:block;padding:.78rem .9rem;border-bottom:1px solid #d8d8d8;color:#064d82;font-weight:700;text-decoration:none}}
.vlrc-publication-embed .publication-page-menu .toc-h3>a{{display:block;padding:.56rem .9rem .56rem 2rem;border-bottom:1px solid #e7e7e7;color:#333;font-size:.92rem;text-decoration:none}}
.vlrc-publication-embed .publication-page-menu .toc-h2>a:hover,.vlrc-publication-embed .publication-page-menu .toc-h2>a:focus-visible,.vlrc-publication-embed .publication-page-menu .toc-h3>a:hover,.vlrc-publication-embed .publication-page-menu .toc-h3>a:focus-visible{{background:#f2f2f2;color:#be1e2b;text-decoration:underline}}
.vlrc-publication-embed .publication-page-menu .toc-h2.is-active>a{{border-left:4px solid #be1e2b;background:#eef4f8}}
.vlrc-publication-embed .btns-pub{{display:flex;flex:0 1 clamp(16rem,22vw,22rem);width:min(100%,22rem);max-width:22rem;min-width:16rem;flex-direction:column;gap:.75rem;text-align:center}}
.vlrc-publication-embed .image-link-pub{{display:block;width:100%;height:auto;margin:0 0 .2rem;border:1px solid #ddd}}
.vlrc-publication-embed .btn-blue,.vlrc-publication-embed .btn-red{{display:flex;min-height:4.5rem;align-items:center;justify-content:space-between;gap:1rem;padding:.9rem 1.25rem;border-radius:.25rem;color:#fff;font-size:clamp(1.15rem,1.55vw,1.5rem);font-weight:700;line-height:1.2;text-decoration:none}}
.vlrc-publication-embed .btn-blue{{background:#064d82}}
.vlrc-publication-embed .btn-red{{background:#b33139}}
.vlrc-publication-embed .btn-blue:hover,.vlrc-publication-embed .btn-blue:focus-visible{{background:#04395f;color:#fff}}
.vlrc-publication-embed .btn-red:hover,.vlrc-publication-embed .btn-red:focus-visible{{background:#92272e;color:#fff}}
.vlrc-publication-embed .btn-icon-pub{{display:block;width:2.7rem;height:2.7rem;flex:0 0 2.7rem;color:currentColor}}
.vlrc-publication-embed .vlrc-reader{{display:none;width:100%;max-width:none;min-height:38rem;margin:0;padding:2rem var(--vlrc-content-gutter) 3rem}}
.vlrc-publication-embed .vlrc-reader:target,.vlrc-publication-embed .vlrc-reader.is-active{{display:block}}
.vlrc-publication-embed.reader-open #publication-landing{{display:none}}
.vlrc-publication-embed .inner-body-content{{display:grid;grid-template-columns:minmax(15rem,18rem) minmax(0,1fr);align-items:start;gap:3rem}}
.vlrc-publication-embed .primary-sidebar{{position:sticky;top:2rem;border:1px solid #ddd;background:#fff}}
.vlrc-publication-embed .sidebar-title{{padding:1rem 1.1rem;background:#064d82;color:#fff}}
.vlrc-publication-embed .h2-title-toc{{margin:0;color:#fff;font-size:1.35rem}}
.vlrc-publication-embed .publication-page-menu .menu{{margin:0}}
.vlrc-publication-embed .publication-page-menu .toc-h2>a{{padding:.66rem .75rem;font-size:.88rem}}
.vlrc-publication-embed .publication-page-menu .toc-h3>a{{padding:.5rem .75rem .5rem 1.45rem;font-size:.8rem}}
.vlrc-publication-embed .main-content{{min-width:0}}
.vlrc-publication-embed .publication-parent-link{{display:inline-block;margin-bottom:.65rem;font-weight:700;text-decoration:none}}
.vlrc-publication-embed .entry-content p{{margin:0 0 1.15rem}}
.vlrc-publication-embed .docling-content-blocks h2{{margin:2.3rem 0 .85rem;color:#064d82;font-size:1.75rem;line-height:1.25}}
.vlrc-publication-embed .docling-content-blocks h3{{margin:1.9rem 0 .7rem;font-size:1.4rem;line-height:1.3}}
.vlrc-publication-embed .docling-content-blocks h4{{margin:1.6rem 0 .6rem;font-size:1.18rem;line-height:1.35}}
.vlrc-publication-embed .docling-content-blocks h5,.vlrc-publication-embed .docling-content-blocks h6{{margin:1.4rem 0 .5rem;font-size:1rem;line-height:1.4}}
.vlrc-publication-embed .document-box-section{{margin:1.75rem 0;border:1px solid #c7c9cc;background:#efedef}}
.vlrc-publication-embed .document-box-section>h3{{margin:0;padding:.7rem 1.1rem;background:#c8c8c8;color:#111;font-size:1.08rem}}
.vlrc-publication-embed .document-box-section-content{{padding:1.1rem 1.35rem .5rem}}
.vlrc-publication-embed .document-box-section-content>p:first-child{{margin-top:0}}
.vlrc-publication-embed .document-box-section--case-study>h3{{background:transparent;color:#666;font-style:italic}}
.vlrc-publication-embed .document-box-section--recommendations{{border-color:#111;background:#efefef}}
.vlrc-publication-embed .document-box-section--recommendations>h3{{background:#050505;color:#fff;text-transform:uppercase}}
.vlrc-publication-embed .source-list{{margin:.5rem 0 1.1rem 2rem;padding-left:1.25rem}}
.vlrc-publication-embed ul.source-list{{list-style:disc outside}}
.vlrc-publication-embed ol.source-list{{list-style:decimal outside}}
.vlrc-publication-embed .source-list .source-list{{margin:.35rem 0 .25rem}}
.vlrc-publication-embed .document-box-section-content .source-list{{margin-left:0;padding-left:1.5rem}}
.vlrc-publication-embed .document-footnote{{padding-left:.75rem;border-left:3px solid #8c929a;color:#505965;font-size:.92em}}
.vlrc-publication-embed .numbered-paragraph{{display:grid;grid-template-columns:minmax(3.5rem,max-content) minmax(0,1fr);gap:.625rem;margin:0 0 1rem}}
.vlrc-publication-embed .numbered-paragraph>span{{color:#be1e2b;font:700 .78rem/1.9 monospace}}
.vlrc-publication-embed .numbered-paragraph p{{margin:0}}
.vlrc-publication-embed .table-scroll{{max-width:100%;overflow-x:auto;margin:1.5rem 0;border:1px solid #ccd1d8}}
.vlrc-publication-embed table{{width:100%;border-collapse:collapse;font-size:.86rem}}
.vlrc-publication-embed caption{{padding:.75rem;background:#e8eef4;text-align:left;font-weight:700}}
.vlrc-publication-embed th,.vlrc-publication-embed td{{min-width:5.6rem;padding:.55rem;border:1px solid #b9c0c9;text-align:left;vertical-align:top}}
.vlrc-publication-embed th{{background:#f2f5f8}}
.vlrc-publication-embed .document-figure-image{{display:block;max-width:100%;width:auto;height:auto;margin:0 auto;border:1px solid #d8dce1}}
.vlrc-publication-embed .figure-unavailable{{min-height:10rem;display:grid;place-items:center;border:.15rem dashed #87919f;background:#f4f6f8;color:#5b6573}}
.vlrc-publication-embed .caption,.vlrc-publication-embed figcaption{{color:#596270;font-size:.85rem}}
.vlrc-publication-embed .document-formula{{margin:1.25rem 0;padding:1rem;border:1px solid #ccd1d8;background:#f7f8f9;font-family:monospace;white-space:pre-wrap;overflow-wrap:anywhere}}
.vlrc-publication-embed .reader-footnotes{{margin-top:2.2rem;padding-top:1rem;border-top:1px solid #c9cdd4}}
.vlrc-publication-embed .reader-footnotes h2{{color:#064d82;font-size:1.4rem}}
.vlrc-publication-embed .reader-footnotes ol{{padding-left:1.75rem}}
.vlrc-publication-embed .reader-pagination{{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-top:2.8rem;padding-top:1.25rem;border-top:1px solid #d8dce1}}
.vlrc-publication-embed .reader-pagination>a,.vlrc-publication-embed .pagination-disabled{{display:flex;flex-direction:column;padding:.75rem;border:1px solid #d8dce1;color:#1d2733;font-size:.84rem;text-decoration:none}}
.vlrc-publication-embed .reader-pagination>a:last-child,.vlrc-publication-embed .pagination-disabled:last-child{{text-align:right}}
.vlrc-publication-embed .reader-pagination span{{color:#6d7482;font-size:.7rem;text-transform:uppercase}}
.vlrc-publication-embed .pagination-disabled{{opacity:.55}}
.vlrc-publication-embed .sr-only{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}
@media(max-width:55rem){{.vlrc-publication-embed .main-column-pub{{gap:2rem}}.vlrc-publication-embed .btns-pub{{width:min(100%,19.3rem);max-width:19.3rem}}.vlrc-publication-embed .inner-body-content{{grid-template-columns:1fr}}.vlrc-publication-embed .primary-sidebar{{position:static}}}}
@media(max-width:36rem){{.vlrc-publication-embed{{--vlrc-content-gutter:1rem}}.vlrc-publication-embed .vlrc-site-publication,.vlrc-publication-embed .vlrc-reader{{padding-top:1.5rem;padding-bottom:2.25rem}}.vlrc-publication-embed .btns-pub{{min-width:0;width:100%;max-width:none;margin:0 auto}}.vlrc-publication-embed .reader-pagination{{grid-template-columns:1fr}}.vlrc-publication-embed .numbered-paragraph{{grid-template-columns:minmax(3rem,max-content) minmax(0,1fr)}}}}
@media(prefers-reduced-motion:reduce){{.vlrc-publication-embed{{scroll-behavior:auto}}}}
@media print{{.vlrc-publication-embed #publication-landing{{display:block!important}}.vlrc-publication-embed .vlrc-reader{{display:block!important;break-before:page}}.vlrc-publication-embed .btns-pub,.vlrc-publication-embed .primary-sidebar,.vlrc-publication-embed .reader-pagination{{display:none}}.vlrc-publication-embed .inner-body-content{{display:block}}.vlrc-publication-embed .table-scroll{{overflow:visible}}}}
</style>
</head>
<body>
<div class="vlrc-publication-embed" data-konverter-publication>
  <a class="skip-link" href="#publication-title">Skip to publication content</a>
  <section class="vlrc-site-publication" id="publication-landing" aria-labelledby="publication-title">
    <article class="publication" role="article" itemscope itemtype="https://schema.org/Report">
      <div class="article-header">
        <h1 class="entry-title single-title" id="publication-title" itemprop="headline" tabindex="-1">{title}</h1>
        <ul class="no-bullet post-byline"><li class="published-date"><span>Published on </span>{published_date}</li></ul>
      </div>
      <div class="main-column-pub">
        <div class="main-content-pub-inner" itemprop="text">
          {summary_html}
          <nav aria-labelledby="publication-contents-heading">
            <h2 class="publication-contents-heading" id="publication-contents-heading">Contents</h2>
            {landing_sections}
          </nav>
        </div>
        <aside class="btns-pub btns-pub-desktop" aria-label="Publication files">
          {cover_html}
          <a class="btn-blue" href="/api/documents/{document_id}/source">
            <span>Download PDF</span>
            <svg class="btn-icon-pub" viewBox="0 0 48 48" role="img" aria-label="PDF document">
              <path d="M11 3h19l8 8v34H11zM30 3v9h8M17 34h14M24 19v12m-5-5 5 5 5-5" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M15 15h12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
            </svg>
          </a>
          <a class="btn-red" href="{project_url}">
            <span>Go to Project</span>
            <svg class="btn-icon-pub" viewBox="0 0 48 48" role="img" aria-label="Project link">
              <path d="m20.5 29.5 7-7m-12.2 12.2-2 2a7.5 7.5 0 0 1-10.6-10.6l7.4-7.4a7.5 7.5 0 0 1 10.6 0m12-5.4 2-2a7.5 7.5 0 1 1 10.6 10.6l-7.4 7.4a7.5 7.5 0 0 1-10.6 0" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </a>
        </aside>
      </div>
    </article>
  </section>
  {reader_sections}
</div>
<script>
(() => {{
  const root = document.querySelector('[data-konverter-publication]');
  const landing = document.getElementById('publication-landing');
  const readers = Array.from(document.querySelectorAll('[data-reader]'));
  const showLanding = (updateHistory = true, moveFocus = true) => {{
    root?.classList.remove('reader-open');
    readers.forEach((reader) => reader.classList.remove('is-active'));
    if (updateHistory && window.location.hash !== '#publication-landing') {{
      window.history.pushState(null, '', '#publication-landing');
    }}
    if (moveFocus) landing?.querySelector('h1')?.focus({{ preventScroll: true }});
  }};
  const openReader = (sectionId, headingId, updateHistory = true) => {{
    const reader = document.querySelector(`[data-reader="${{CSS.escape(sectionId)}}"]`);
    if (!reader) return;
    root?.classList.add('reader-open');
    readers.forEach((candidate) => candidate.classList.toggle('is-active', candidate === reader));
    if (updateHistory && window.location.hash !== `#reader-${{sectionId}}`) {{
      window.history.pushState({{ sectionId, headingId }}, '', `#reader-${{sectionId}}`);
    }}
    reader.focus({{ preventScroll: true }});
    if (headingId) {{
      const heading = document.getElementById(headingId);
      heading?.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }} else reader.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
  }};
  document.querySelectorAll('[data-open-section]').forEach((link) => link.addEventListener('click', (event) => {{
    event.preventDefault();
    openReader(link.getAttribute('data-open-section'), link.getAttribute('data-heading'));
  }}));
  document.querySelectorAll('[data-close-reader]').forEach((link) => link.addEventListener('click', (event) => {{
    event.preventDefault();
    showLanding();
    landing?.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
  }}));
  const syncFromLocation = () => {{
    const match = window.location.hash.match(/^#reader-(.+)$/);
    if (match) openReader(decodeURIComponent(match[1]), window.history.state?.headingId, false);
    else showLanding(false, false);
  }};
  window.addEventListener('popstate', syncFromLocation);
  syncFromLocation();
}})();
</script>
</body>
</html>"""


# The reviewer preview's report-card design is the publishing contract for the
# downloadable HTML. This late binding keeps the publication/JSON-LD builders
# in this module while the sizeable HTML template remains isolated and testable.
from .preview_html import build_accessible_html as build_accessible_html
