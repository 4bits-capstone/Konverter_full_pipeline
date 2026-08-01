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


def _precise_summary(values: list[str]) -> str:
    sentences: list[tuple[int, str]] = []
    seen: set[str] = set()
    for order, value in enumerate(values):
        normalized = re.sub(r"\s+", " ", value).strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized):
            sentence = sentence.strip()
            key = sentence.casefold()
            if len(sentence) < 45 or key in seen:
                continue
            seen.add(key)
            score = 0
            if re.match(
                r"^(?:this|the)\s+(?:report|publication|review|commission)\b",
                sentence,
                re.IGNORECASE,
            ):
                score += 7
            score += 3 * len(
                re.findall(
                    r"\b(?:recommend|propos|establish|enable|examin|explain|set out|conclud|find|reform|address)\w*",
                    sentence,
                    re.IGNORECASE,
                )
            )
            if re.search(r"\b\d+\b", sentence):
                score += 2
            if 75 <= len(sentence) <= 260:
                score += 2
            if re.match(r"^(?:it|they|these|this approach)\b", sentence, re.IGNORECASE):
                score -= 3
            sentences.append((score * 10_000 - order, sentence))

    if not sentences:
        normalized = re.sub(r"\s+", " ", " ".join(values)).strip()
        return normalized if len(normalized) <= 320 else f"{normalized[:317].rstrip()}…"

    selected = [sentence for _, sentence in sorted(sentences, reverse=True)[:2]]
    selected.sort(
        key=lambda sentence: next(
            index
            for index, value in enumerate(values)
            if sentence in re.sub(r"\s+", " ", value).strip()
        )
    )
    summary = " ".join(selected)
    if len(summary) <= 360:
        return summary
    first = selected[0]
    return first if len(first) <= 360 else f"{first[:357].rstrip()}…"


def _publication_summary(blocks: list[dict[str, Any]], source_name: str) -> str:
    ordered = sorted(blocks, key=lambda value: int(value.get("order", 0)))
    executive_index = next(
        (
            index
            for index, block in enumerate(ordered)
            if str(block.get("label", "")).startswith("section_header_")
            and str(block.get("text", "")).strip().casefold() == "executive summary"
        ),
        -1,
    )
    if executive_index >= 0:
        candidates: list[str] = []
        for block in ordered[executive_index + 1 :]:
            label = str(block.get("label", ""))
            text = str(block.get("text", "")).strip()
            if label == "chapter_title" or (
                label == "section_header_1"
                and text.casefold() in {"recommendation", "recommendations"}
            ):
                break
            if label == "text" and len(text) >= 80:
                candidates.append(text)
            candidates.extend(
                str(item).strip()
                for item in block.get("list_items") or []
                if len(str(item).strip()) >= 80
            )
        if candidates:
            return _precise_summary(candidates)

    first_chapter_index = next(
        (
            index
            for index, block in enumerate(ordered)
            if block.get("label") == "chapter_title"
            and re.match(
                r"^(?:chapter\s+)?1\.\s+", str(block.get("text", "")), re.IGNORECASE
            )
        ),
        -1,
    )
    if first_chapter_index >= 0:
        candidates = []
        for block in ordered[first_chapter_index + 1 :]:
            if block.get("label") == "chapter_title":
                break
            text = str(block.get("text", "")).strip()
            if block.get("label") == "text" and len(text) >= 80:
                candidates.append(text)
            for item in block.get("list_items") or []:
                item_text = re.sub(r"^\d+(?:\.\d+)+\s+", "", str(item)).strip()
                if len(item_text) >= 80:
                    candidates.append(item_text)
        if candidates:
            return _precise_summary(candidates)

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
    first_numbered_chapter = next(
        (
            index
            for index, section in enumerate(sections)
            if re.match(
                r"^(?:chapter\s+)?1\.\s+",
                str(section.get("displayTitle", "")),
                re.IGNORECASE,
            )
        ),
        -1,
    )
    candidates = (
        sections[first_numbered_chapter:] if first_numbered_chapter >= 0 else sections
    )
    return [
        section
        for section in candidates
        if section.get("id") != "front-matter"
        and str(section.get("displayTitle", "")).strip().casefold()
        not in {"front matter", "contents", "table of contents"}
    ]


def build_publication(
    blocks: list[dict[str, Any]],
    record: dict[str, Any],
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
        "page": 1,
        "blocks": [],
        "headings": [],
        "footnotes": [],
    }
    has_chapter_titles = any(block.get("label") == "chapter_title" for block in blocks)

    def finish_current() -> None:
        if current["blocks"] or current["footnotes"]:
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

        starts_section = label == "chapter_title" or (
            not has_chapter_titles and label == "section_header_1"
        )
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
            }
            current["blocks"].append(heading)
            continue

        if label == "document_index":
            continue

        if label == "table":
            table = block.get("table_data") or {
                "headers": ["Column 1"],
                "rows": [[text]],
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
            current["blocks"].append(
                {
                    "type": "table",
                    "id": _unique_slug(f"table-{len(current['blocks']) + 1}", counts),
                    "caption": "Extracted table",
                    "rows": rows,
                    "page": page,
                }
            )
            continue

        if label in {"list", "list_item"}:
            list_items = block.get("list_items") or _split_lines(text)
            pending_list_items: list[str] = []

            def flush_pending_list() -> None:
                if pending_list_items:
                    current["blocks"].append(
                        {
                            "type": "list",
                            "style": "unordered",
                            "items": [{"text": value} for value in pending_list_items],
                            "page": page,
                        }
                    )
                    pending_list_items.clear()

            for value in list_items:
                item_text = re.sub(r"^[•\-–]\s*", "", str(value)).strip()
                numbered_item = re.match(
                    r"^(\d+(?:\.\d+)+)\s+(.+)$", item_text, re.DOTALL
                )
                if numbered_item:
                    flush_pending_list()
                    current["blocks"].append(
                        {
                            "type": "paragraph",
                            "text": numbered_item.group(2),
                            "number": numbered_item.group(1),
                            "page": page,
                        }
                    )
                elif item_text:
                    pending_list_items.append(item_text)
            flush_pending_list()
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
    reader_sections = _reader_sections(sections)
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
        "summary": [_publication_summary(blocks, source_name)],
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
    figures = [
        block
        for section in publication.get("sections", [])
        for block in section.get("blocks", [])
        if block.get("type") == "figure"
    ]
    all_figures_captioned = all(str(f.get("caption", "")).strip() for f in figures)
    features = ["structuralNavigation", "tableOfContents", "readingOrder"]
    if all_figures_captioned:
        features.append("alternativeText")
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
    }


def build_json_ld(
    document_id: str,
    publication: dict[str, Any],
    metadata: dict[str, Any],
    *,
    site_url: str = "",
    site_name: str = "",
    page_url_template: str = "",
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
    html_url = f"/api/documents/{document_id}/exports/accessible.html"

    page_url = ""
    if page_url_template:
        page_url = page_url_template.replace(
            "{slug}", _slug(title) or document_id
        ).replace("{id}", document_id)
    page_id = page_url or f"#webpage-{document_id}"
    breadcrumb_id = (
        f"{page_url}#breadcrumb" if page_url else f"#breadcrumb-{document_id}"
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
            "dateModified": generated_at,
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
                    "contentUrl": f"/api/documents/{document_id}/source",
                },
                {
                    "@type": "MediaObject",
                    "encodingFormat": "text/html",
                    "contentUrl": html_url,
                },
            ],
            "mainEntityOfPage": {"@id": page_id},
            "hasPart": [
                {
                    "@type": "Chapter",
                    "@id": f"{report_id}#{section['id']}",
                    "isPartOf": {"@id": report_id},
                    "name": section["displayTitle"],
                    "position": index + 1,
                }
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
            "potentialAction": [
                {"@type": "ReadAction", "target": [page_url or html_url]}
            ],
        }
    )

    graph: list[dict[str, Any]] = [report, web_page, *organisation_nodes]
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
        tag = "ol" if block.get("style") == "ordered" else "ul"
        items = "".join(
            f"<li>{html.escape(str(item.get('text', '')))}</li>"
            for item in block.get("items", [])
        )
        return f"<{tag}>{items}</{tag}>"
    if block_type == "table":
        caption = html.escape(str(block.get("caption", "Extracted table")))
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
        return (
            f'<div class="table-scroll" tabindex="0" role="region" aria-label="{caption}; scroll horizontally when needed">'
            f'<table id="{html.escape(str(block.get("id", "")))}"><caption>{caption}</caption>{head_html}<tbody>{body_html}</tbody></table></div>'
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
        return (
            f'<details class="reader-footnotes"><summary>References and footnotes ({len(footnotes)})</summary><ol>'
            + "".join(
                f'<li id="{html.escape(str(note["id"]))}">{html.escape(str(note["text"]))}</li>'
                for note in footnotes
            )
            + "</ol></details>"
        )

    def render_landing_section(section: dict[str, Any], index: int) -> str:
        section_id = html.escape(str(section["id"]))
        major_headings = [
            heading
            for heading in section.get("headings", [])
            if int(heading.get("level", 2)) == 2
        ]
        links = (
            f'<li class="read-full"><a href="#reader-{section_id}" data-open-section="{section_id}">'
            "Read full section</a></li>"
            + "".join(
                f'<li><a href="#reader-{section_id}" data-open-section="{section_id}" '
                f'data-heading="{html.escape(str(heading["id"]))}">{html.escape(str(heading["text"]))}</a></li>'
                for heading in major_headings
            )
        )
        open_attribute = " open" if index == 0 else ""
        return (
            f'<details class="vlrc-accordion-item"{open_attribute}>'
            f'<summary><span>{html.escape(str(section["displayTitle"]))}</span><span aria-hidden="true">⌄</span></summary>'
            f"<ul>{links}</ul></details>"
        )

    def render_reader(section: dict[str, Any], index: int) -> str:
        section_id = html.escape(str(section["id"]))
        heading_links = "".join(
            f'<li class="heading-level-{int(heading.get("level", 2))}">'
            f'<a href="#{html.escape(str(heading["id"]))}" data-reader-heading="{html.escape(str(heading["id"]))}">'
            f"{html.escape(str(heading['text']))}</a></li>"
            for heading in section.get("headings", [])
        )
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
            f'<section class="vlrc-reader" id="reader-{section_id}" data-reader="{section_id}" tabindex="-1">'
            '<nav class="vlrc-reader-breadcrumb" aria-label="Breadcrumb">'
            f'<a href="#publication-landing" data-close-reader>← {title}</a>'
            f'<span aria-hidden="true">›</span><span aria-current="page">{html.escape(str(section["displayTitle"]))}</span></nav>'
            '<div class="vlrc-reader-layout">'
            '<nav class="vlrc-reader-nav" aria-label="In this section"><h2>In this section</h2>'
            f"<ul>{heading_links}</ul></nav>"
            '<div class="vlrc-reader-content">'
            f'<div class="chapter-label">{title}</div>'
            f'<h1 tabindex="-1">{html.escape(str(section["displayTitle"]))}</h1>'
            f'<div class="docling-content-blocks">{"".join(_render_block(block, figure_directory) for block in section.get("blocks", []))}</div>'
            f"{render_footnotes(section)}"
            f'<nav class="reader-pagination" aria-label="Document section pagination">{previous_link}{next_link}</nav>'
            "</div></div></section>"
        )

    title = html.escape(
        str(
            metadata.get("title")
            or publication.get("sourceName")
            or "Accessible document"
        )
    )
    jurisdiction = html.escape(str(metadata.get("jurisdiction", "")))
    published_date = html.escape(
        _format_published_date(metadata.get("published_date", ""))
    )
    safe_json_ld = json.dumps(json_ld, ensure_ascii=False).replace("<", "\\u003c")
    logo_uri = _data_uri(logo_path)
    cover_uri = _data_uri(cover_path)
    summaries = publication.get("summary", [])
    summary_html = "".join(
        f'<p class="vlrc-summary publication-summary">{html.escape(str(value))}</p>'
        for value in summaries
    )
    logo_html = (
        f'<img src="{logo_uri}" alt="Victorian Law Reform Commission logo">'
        if logo_uri
        else "<strong>Victorian Law Reform Commission</strong>"
    )
    cover_html = (
        f'<img class="vlrc-cover publication-cover" src="{cover_uri}" alt="Cover of {title}">'
        if cover_uri
        else ""
    )
    landing_sections = "".join(
        render_landing_section(section, index) for index, section in enumerate(sections)
    )
    reader_sections = "".join(
        render_reader(section, index) for index, section in enumerate(sections)
    )
    pages = int(publication.get("stats", {}).get("pages", 0))

    return f"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script type="application/ld+json">{safe_json_ld}</script>
<style>
:root{{font-family:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;color:#151a23;background:#fff;line-height:1.65}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0}}
a{{color:#165487}}
.skip-link{{position:absolute;left:1rem;top:-5rem;z-index:10;padding:.75rem 1rem;background:#fff;color:#165487;font-weight:700}}
.skip-link:focus{{top:1rem}}
a:focus-visible,button:focus-visible,summary:focus-visible,[tabindex="0"]:focus-visible{{outline:3px solid #165487;outline-offset:2px;border-radius:2px}}
.vlrc-masthead a:focus-visible,.vlrc-accordion-item[open]>summary:focus-visible{{outline-color:#fff}}
.back-to-top{{position:fixed;right:22px;bottom:22px;z-index:60;display:none;align-items:center;gap:8px;min-height:44px;min-width:44px;padding:10px 16px;border:0;border-radius:999px;background:#165487;color:#fff;font:700 13px/1 "IBM Plex Sans","Segoe UI",system-ui,sans-serif;cursor:pointer;box-shadow:0 8px 22px rgba(22,35,61,.28)}}
.back-to-top.is-visible{{display:inline-flex}}
.back-to-top:hover{{background:#12466f}}
.vlrc-preview{{width:100%;min-height:100vh;margin:0;background:#fff}}
.vlrc-masthead{{min-height:96px;padding:18px 28px;background:linear-gradient(115deg,#155a91 0%,#234a8f 45%,#7a2b2b 100%);color:#fff;display:flex;align-items:center;justify-content:space-between;gap:20px}}
.vlrc-masthead img{{display:block;width:150px;height:auto}}
.vlrc-masthead-label{{border-left:1px solid rgba(255,255,255,.4);padding-left:18px;font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase}}
.vlrc-preview-body{{width:min(100%,74rem);margin:0 auto;padding:22px 28px 42px}}
.vlrc-publication-layout{{display:grid;grid-template-columns:minmax(0,1fr) 210px;align-items:start;gap:34px;padding-top:30px}}
.jurisdiction{{font-size:11px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:#7a2b2b}}
h1{{font-size:clamp(28px,4vw,42px);line-height:1.08;letter-spacing:-.035em;margin:10px 0 20px;max-width:22ch}}
.published-date{{margin:0 0 20px;color:#6d7482;font-size:12.5px}}
.publication-summary{{max-width:74ch;margin:0 0 12px;color:#2c3442;font-size:14px;line-height:1.7}}
.vlrc-contents{{margin-top:34px}}
.vlrc-accordion-item{{border-bottom:1px solid #9ea3ab}}
.vlrc-accordion-item>summary{{cursor:pointer;list-style:none;display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:48px;padding:12px 14px;background:#fff;font-size:13px;font-weight:700}}
summary::-webkit-details-marker{{display:none}}
.vlrc-accordion-item>summary:hover,.vlrc-accordion-item>summary:focus-visible{{background:#f4f7fa;color:#12466f}}
.vlrc-accordion-item[open]>summary{{background:#165487;color:#fff}}
.vlrc-accordion-item[open]>summary>span:last-child{{transform:rotate(180deg)}}
.vlrc-accordion-item ul{{margin:0;padding:0;list-style:none;background:#f7f8f9}}
.vlrc-accordion-item li{{border-bottom:1px solid #e0e3e7}}
.vlrc-accordion-item li:last-child{{border-bottom:0}}
.vlrc-accordion-item a{{display:block;padding:10px 16px 10px 28px;font-size:12.5px;text-decoration:none}}
.vlrc-accordion-item a:hover,.vlrc-accordion-item a:focus-visible{{background:#eaf1f7;text-decoration:underline}}
.vlrc-accordion-item .read-full a{{padding-left:16px;font-weight:700}}
.vlrc-publication-aside{{position:sticky;top:24px;display:flex;flex-direction:column;gap:12px}}
.publication-cover{{display:block;width:100%;height:auto;border:1px solid #d3d5d8;box-shadow:0 8px 22px rgba(22,35,61,.14)}}
.vlrc-download{{min-height:46px;padding:11px 14px;background:#165487;color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;text-decoration:none}}
.vlrc-report-card{{padding:13px 14px;background:#7a2b2b;color:#fff;display:flex;flex-direction:column}}
.vlrc-report-card span{{color:#f0dede;font-size:11px}}
.vlrc-reader{{display:none;min-height:620px;width:min(100%,90rem);margin:0 auto}}
.vlrc-reader:target,.vlrc-reader.is-active{{display:block}}
.vlrc-reader-breadcrumb{{display:flex;align-items:center;gap:9px;padding:14px 26px;border-bottom:1px solid #d8dce1;color:#6d7482;font-size:12px}}
.vlrc-reader-breadcrumb a{{font-weight:700;text-decoration:none}}
.vlrc-reader-layout{{display:grid;grid-template-columns:220px minmax(0,1fr);align-items:start}}
.vlrc-reader-nav{{position:sticky;top:0;max-height:100vh;overflow:auto;padding:24px 18px;border-right:1px solid #d8dce1;background:#f7f8f9}}
.vlrc-reader-nav h2{{margin:0 0 12px;font-size:14px}}
.vlrc-reader-nav ul{{margin:0;padding:0;list-style:none}}
.vlrc-reader-nav li+li{{margin-top:2px}}
.vlrc-reader-nav a{{display:block;padding:7px 8px;border-left:3px solid transparent;color:#46505d;font-size:12px;line-height:1.35;text-decoration:none}}
.vlrc-reader-nav a:hover,.vlrc-reader-nav a:focus-visible,.vlrc-reader-nav a[aria-current="location"]{{border-left-color:#165487;background:#e7eef5;color:#12466f}}
.vlrc-reader-nav .heading-level-3 a{{padding-left:18px;font-size:11.5px}}
.vlrc-reader-nav .heading-level-4 a,.vlrc-reader-nav .heading-level-5 a,.vlrc-reader-nav .heading-level-6 a{{padding-left:28px;font-size:11px}}
.vlrc-reader-content{{min-width:0;padding:34px 40px 46px}}
.chapter-label{{color:#7a2b2b;font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase}}
.vlrc-reader-content>h1{{max-width:none;margin-bottom:32px}}
.docling-content-blocks p{{color:#303744;font-size:14px;line-height:1.72}}
.docling-content-blocks h2{{margin:38px 0 14px;font-size:24px;line-height:1.2}}
.docling-content-blocks h3{{margin:30px 0 12px;font-size:20px;line-height:1.25}}
.docling-content-blocks h4,.docling-content-blocks h5,.docling-content-blocks h6{{margin:24px 0 10px;font-size:17px;line-height:1.3}}
.numbered-paragraph{{display:grid;grid-template-columns:minmax(3.5rem,max-content) minmax(0,1fr);gap:.625rem;margin:0 0 1rem}}
.numbered-paragraph>span{{font:700 11.5px/1.9 monospace;color:#7a2b2b}}
.numbered-paragraph p{{margin:0}}
.table-scroll{{max-width:100%;overflow-x:auto;margin:1.5rem 0;border:1px solid #ccd1d8}}
table{{border-collapse:collapse;width:100%;font-size:.78rem}}
caption{{text-align:left;font-weight:700;padding:.75rem;background:#e8eef4}}
th,td{{min-width:90px;border:1px solid #b9c0c9;padding:.55rem;text-align:left;vertical-align:top}}
th{{background:#f2f5f8}}
.document-figure-image{{display:block;max-width:100%;width:auto;height:auto;margin:0 auto;border:1px solid #d8dce1}}
.figure-unavailable{{min-height:10rem;display:grid;place-items:center;border:.15rem dashed #87919f;background:#f4f6f8;color:#5b6573}}
.caption,figcaption{{font-size:.85rem;color:#596270}}
.document-formula{{margin:1.25rem 0;padding:1rem;border:1px solid #ccd1d8;background:#f7f8f9;font-family:"IBM Plex Mono",monospace;white-space:pre-wrap;overflow-wrap:anywhere}}
.reader-footnotes{{margin-top:34px;border-top:1px solid #c9cdd4;padding-top:16px}}
.reader-footnotes summary{{cursor:pointer;font-weight:700}}
.reader-footnotes ol{{padding-left:28px}}
.reader-pagination{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:46px;padding-top:20px;border-top:1px solid #d8dce1}}
.reader-pagination>a,.pagination-disabled{{display:flex;flex-direction:column;padding:12px;border:1px solid #d8dce1;color:#1d2733;font-size:12px;text-decoration:none}}
.reader-pagination>a:last-child,.pagination-disabled:last-child{{text-align:right}}
.reader-pagination span{{color:#6d7482;font-size:10px;text-transform:uppercase}}
.pagination-disabled{{opacity:.55}}
.source-footer{{width:100%;margin:0;padding:1.5rem max(28px,calc((100% - 74rem)/2 + 28px));border-top:1px solid #c9cdd4;background:#fff;color:#596270;font-size:.8rem}}
.sr-only{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}
body.reader-open #publication-landing{{display:none}}
@media(max-width:52rem){{.vlrc-publication-layout{{grid-template-columns:1fr}}.vlrc-publication-aside{{position:static;display:grid;grid-template-columns:minmax(150px,210px) 1fr;align-items:start}}.vlrc-reader-layout{{grid-template-columns:1fr}}.vlrc-reader-nav{{position:static;max-height:none;border-right:0;border-bottom:1px solid #d8dce1}}}}
@media(max-width:36rem){{.vlrc-preview{{width:100%;margin:0;box-shadow:none}}.vlrc-masthead{{min-height:80px;padding:15px 18px}}.vlrc-preview-body{{padding-left:18px;padding-right:18px}}.vlrc-publication-aside{{display:flex}}.publication-cover{{width:min(100%,280px);align-self:center}}.vlrc-reader-content{{padding:26px 18px 36px}}.numbered-paragraph{{grid-template-columns:minmax(3rem,max-content) minmax(0,1fr)}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
@media print{{.back-to-top{{display:none!important}}body{{background:#fff}}.vlrc-preview{{width:100%;margin:0;box-shadow:none}}#publication-landing{{display:block!important}}.vlrc-reader{{display:block!important;break-before:page}}.vlrc-publication-aside,.vlrc-reader-nav,.reader-pagination{{display:none}}.table-scroll{{overflow:visible}}}}
</style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<main class="vlrc-preview" id="main-content">
  <header class="vlrc-masthead">{logo_html}<span class="vlrc-masthead-label">Publication</span></header>
  <section class="vlrc-preview-body" id="publication-landing">
    <div class="vlrc-publication-layout">
      <div class="vlrc-publication-main">
        <div class="jurisdiction">{jurisdiction}</div>
        <h1 tabindex="-1">{title}</h1>
        <p class="vlrc-published-date published-date">Published on {published_date}.</p>
        {summary_html}
        <section class="vlrc-contents" aria-label="Document chapters">
          <div class="vlrc-accordion">{landing_sections}</div>
        </section>
      </div>
      <aside class="vlrc-publication-aside" aria-label="Publication files">
        {cover_html}
        <a class="vlrc-download" href="/api/documents/{document_id}/source">Download PDF</a>
        <div class="vlrc-report-card"><strong>Report</strong><span>{pages} pages · {published_date}</span></div>
      </aside>
    </div>
  </section>
  {reader_sections}
</main>
<button class="back-to-top" type="button" aria-label="Back to top of page">↑ Top</button>
<footer class="source-footer">Accessible HTML generated from reviewed Docling data. Schema.org JSON-LD is embedded in this page.</footer>
<script>
(() => {{
  const landing = document.getElementById('publication-landing');
  const readers = Array.from(document.querySelectorAll('[data-reader]'));
  const showLanding = () => {{
    document.body.classList.remove('reader-open');
    readers.forEach((reader) => reader.classList.remove('is-active'));
    landing?.querySelector('h1')?.focus({{ preventScroll: true }});
  }};
  const openReader = (sectionId, headingId) => {{
    const reader = document.querySelector(`[data-reader="${{CSS.escape(sectionId)}}"]`);
    if (!reader) return;
    document.body.classList.add('reader-open');
    readers.forEach((candidate) => candidate.classList.toggle('is-active', candidate === reader));
    reader.focus({{ preventScroll: true }});
    if (headingId) {{
      const heading = document.getElementById(headingId);
      heading?.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      reader.querySelectorAll('[data-reader-heading]').forEach((link) => {{
        if (link.getAttribute('data-reader-heading') === headingId) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      }});
    }} else window.scrollTo({{ top: 0, behavior: 'smooth' }});
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
  document.querySelectorAll('[data-reader-heading]').forEach((link) => link.addEventListener('click', () => {{
    const reader = link.closest('[data-reader]');
    reader?.querySelectorAll('[data-reader-heading]').forEach((candidate) => candidate.removeAttribute('aria-current'));
    link.setAttribute('aria-current', 'location');
  }}));
  const backToTop = document.querySelector('.back-to-top');
  if (backToTop) {{
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const toggle = () => backToTop.classList.toggle('is-visible', window.scrollY > 480);
    window.addEventListener('scroll', toggle, {{ passive: true }});
    toggle();
    backToTop.addEventListener('click', () => {{
      window.scrollTo({{ top: 0, behavior: prefersReducedMotion.matches ? 'auto' : 'smooth' }});
      const activeReader = document.querySelector('[data-reader].is-active');
      (activeReader ?? landing)?.querySelector('h1')?.focus({{ preventScroll: true }});
    }});
  }}
}})();
</script>
</body>
</html>"""
