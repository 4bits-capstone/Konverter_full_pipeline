from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .config import Settings

FIRST_PAGE = 1
LAST_PAGE = 8
MONTHS = (
    r"(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)"
)
MONTH_NUMBERS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def clean_line(line: Any) -> str:
    """Remove markup noise and normalise whitespace without changing wording."""
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", str(line or ""))
    value = re.sub(r"<!--.*?-->", "", value)
    return re.sub(r"\s+", " ", value).strip(" |\t")


def _first_page(item: dict[str, Any]) -> int | None:
    provenance = item.get("prov") or []
    if not provenance:
        return None
    try:
        return int(provenance[0].get("page_no"))
    except (TypeError, ValueError):
        return None


def pages_from_docling(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Build rule input from the existing Docling result without reconverting."""
    pages: dict[int, list[str]] = {}
    for item in document.get("texts") or []:
        page_number = _first_page(item)
        if page_number is None or not FIRST_PAGE <= page_number <= LAST_PAGE:
            continue
        text = clean_line(item.get("text"))
        if text:
            pages.setdefault(page_number, []).append(text)

    for table in document.get("tables") or []:
        page_number = _first_page(table)
        if page_number is None or not FIRST_PAGE <= page_number <= LAST_PAGE:
            continue
        for cell in (table.get("data") or {}).get("table_cells") or []:
            text = clean_line(cell.get("text"))
            if text:
                pages.setdefault(page_number, []).append(text)

    return [
        {"number": page_number, "text": "\n".join(lines)}
        for page_number, lines in sorted(pages.items())
    ]


def page_lines(pages: Iterable[dict[str, Any]]) -> Iterable[tuple[int, str]]:
    for page in pages:
        for raw_line in str(page.get("text") or "").splitlines():
            line = clean_line(raw_line)
            if line:
                yield int(page["number"]), line


def metadata_field(
    value: Any,
    source_page: int | None,
    method: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "value": value,
        "source_page": source_page,
        "method": method,
        "confidence": confidence,
    }


def normalise_title(title: Any) -> str:
    value = clean_line(title)
    value = re.split(
        r"\s*/\s*Victorian Law Reform Commission\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.sub(
        rf"\s*[|\-–—:]?\s*(?:final\s+)?report(?:\s+\d+)?"
        rf"(?:\s*[|\-–—]?\s*{MONTHS}\s+\d{{4}})?\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"\s+[|\-–—]?\s*{MONTHS}\s+\d{{4}}\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+([:;,.])", r"\1", value).strip(" .:;|-–—")
    value = re.sub(r"\b([A-Z])\s+([a-z]{3,})\b", r"\1\2", value)
    if value.isupper() or re.search(r"[a-z][A-Z]\b", value):
        value = value.title()

    words = value.split()
    minor_words = {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
    }
    for index in range(1, len(words)):
        if words[index].casefold() in minor_words:
            words[index] = words[index].lower()
    return " ".join(words)


def _filename_title(pdf_path: Path) -> str:
    title = pdf_path.stem.replace("_", " ").replace("-", " ")
    title = re.sub(r"\bVLRC\b", "", title, flags=re.IGNORECASE)
    title = re.sub(
        r"\b(?:forweb|web|fnl|parl)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return normalise_title(title)


def extract_title(
    pages: list[dict[str, Any]],
    pdf_path: Path,
) -> dict[str, Any]:
    lines = list(page_lines(pages))
    for position, (page_number, line) in enumerate(lines):
        match = re.match(
            r"(?:title\s*:\s*)?(.+?)(?::\s*report)?\s*/\s*"
            r"Victorian Law Reform Commission\b",
            line,
            re.IGNORECASE,
        )
        if match:
            title = normalise_title(match.group(1))
            if title:
                return metadata_field(
                    title,
                    page_number,
                    "cataloguing_title_rule",
                    0.98,
                )

        match = re.match(r"title\s*:\s*(.+)$", line, re.IGNORECASE)
        if match:
            title = normalise_title(match.group(1))
            if title:
                return metadata_field(
                    title,
                    page_number,
                    "labelled_title_rule",
                    0.96,
                )

        if re.fullmatch(r"title\s*:?", line, re.IGNORECASE):
            next_line = lines[position + 1] if position + 1 < len(lines) else None
            if next_line and next_line[0] == page_number:
                title = normalise_title(next_line[1])
                if title:
                    return metadata_field(
                        title,
                        page_number,
                        "labelled_title_rule",
                        0.96,
                    )

    ignore = re.compile(
        rf"^(?:published by|contents?|warning|commission|"
        rf"victorian law reform commission|report\s+{MONTHS}|"
        rf"a community law reform project|gpo\s*box|level\s+\d+|"
        rf"telephone|freecall|facsimile|email|web|www\.|chair|commissioners?)\b",
        re.IGNORECASE,
    )
    best: tuple[int, int, int, str] | None = None
    for position, (page_number, line) in enumerate(lines[:80]):
        if ignore.search(line) or len(line) < 5 or len(line) > 180:
            continue
        if re.search(
            r"(?:@|www\.|\.gov|copyright|ISBN|Series:)",
            line,
            re.IGNORECASE,
        ):
            continue

        score = 4 if position < 12 else 0
        if re.search(r"\b(?:final\s+)?report(?:\s+\d+)?\b", line, re.IGNORECASE):
            score += 4
        if 2 <= len(line.split()) <= 14:
            score += 2
        if re.search(r"\b(?:the|of|and|in|for|act|justice|law)\b", line, re.IGNORECASE):
            score += 1

        title = normalise_title(line)
        if len(title.split()) < 2:
            continue
        candidate = (score, -position, page_number, title)
        if best is None or candidate > best:
            best = candidate

    if best and best[0] >= 5:
        chosen = best[3].casefold()
        pages_with_title = {
            page_number
            for page_number, line in lines
            if chosen and chosen in normalise_title(line).casefold()
        }
        repeats = len(pages_with_title)
        score = 0.82 if repeats <= 1 else min(0.93, 0.86 + 0.03 * (repeats - 1))
        field = metadata_field(best[3], best[2], "cover_title_rule", score)
        field["corroboration"] = f"seen on {repeats} of the first {LAST_PAGE} pages"
        return field

    fallback = _filename_title(pdf_path)
    return metadata_field(
        fallback or None,
        None,
        "filename_fallback",
        0.45 if fallback else 0.0,
    )


def extract_publisher(pages: list[dict[str, Any]]) -> dict[str, Any]:
    for page_number, line in page_lines(pages):
        match = re.search(
            r"\bpublished by\s+(?:the\s+)?(.+)$",
            line,
            re.IGNORECASE,
        )
        if match:
            publisher = re.split(r"[.;]", match.group(1), maxsplit=1)[0].strip()
            repeated_sentence = re.search(
                r"\s+(?:The|This)\s+(?=[A-Z])",
                publisher,
            )
            if repeated_sentence:
                publisher = publisher[: repeated_sentence.start()].strip()
            publisher = re.split(
                r"\b(?:the commission|copyright|isbn|series)\b",
                publisher,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()
            if publisher:
                return metadata_field(
                    publisher,
                    page_number,
                    "published_by_rule",
                    0.98,
                )

    organisation_pages = [
        page_number
        for page_number, line in page_lines(pages)
        if re.search(r"\bVictorian Law Reform Commission\b", line, re.IGNORECASE)
    ]
    if organisation_pages:
        occurrences = len(organisation_pages)
        score = 0.78 if occurrences == 1 else 0.84 if occurrences == 2 else 0.90
        field = metadata_field(
            "Victorian Law Reform Commission",
            organisation_pages[0],
            "organisation_name_rule",
            score,
        )
        field["corroboration"] = f"organisation name found {occurrences} time(s)"
        return field

    return metadata_field(None, None, "not_found", 0.0)


def _normalise_date(value: str) -> str:
    value = clean_line(value)
    month_match = re.fullmatch(
        rf"({MONTHS})\s+((?:19|20)\d{{2}})",
        value,
        re.IGNORECASE,
    )
    if month_match:
        month = MONTH_NUMBERS[month_match.group(1).casefold()]
        return f"{month_match.group(2)}-{month:02d}"

    day_month_match = re.fullmatch(
        rf"(\d{{1,2}})\s+({MONTHS})\s+((?:19|20)\d{{2}})",
        value,
        re.IGNORECASE,
    )
    if day_month_match:
        month = MONTH_NUMBERS[day_month_match.group(2).casefold()]
        return (
            f"{day_month_match.group(3)}-{month:02d}-"
            f"{int(day_month_match.group(1)):02d}"
        )
    return value


def extract_date(
    pages: list[dict[str, Any]],
    pdf_path: Path,
) -> dict[str, Any]:
    lines = list(page_lines(pages))
    patterns = [
        (
            rf"\b(?:final\s+)?report\s*[|\-–—:]?\s*"
            rf"((?:\d{{1,2}}\s+)?{MONTHS}\s+\d{{4}})\b",
            "cover_report_date_rule",
            0.98,
        ),
        (
            rf"^((?:\d{{1,2}}\s+)?{MONTHS}\s+\d{{4}})$",
            "cover_date_rule",
            0.96,
        ),
        (
            rf"©\s*((?:\d{{1,2}}\s+)?{MONTHS}\s+\d{{4}})\b",
            "copyright_date_rule",
            0.94,
        ),
        (
            rf"\bpublished[^\n]*?\b((?:\d{{1,2}}\s+)?{MONTHS}\s+\d{{4}})\b",
            "publication_date_rule",
            0.90,
        ),
    ]
    for pattern, method, confidence in patterns:
        for page_number, line in lines:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return metadata_field(
                    _normalise_date(match.group(1)),
                    page_number,
                    method,
                    confidence,
                )

    for page_number, line in lines:
        match = re.search(r"©[^\n]*?\b((?:19|20)\d{2})\b", line)
        if match:
            return metadata_field(
                match.group(1),
                page_number,
                "copyright_year_rule",
                0.82,
            )

    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", pdf_path.stem)
    if match:
        return metadata_field(
            match.group(1),
            None,
            "filename_year_fallback",
            0.45,
        )
    return metadata_field(None, None, "not_found", 0.0)


def extract_jurisdiction(pages: list[dict[str, Any]]) -> dict[str, Any]:
    state_rules = [
        (r"\bVictoria(?:n)?\b|\(Vic\)", "Victoria, Australia"),
        (r"\bNew South Wales\b|\(NSW\)", "New South Wales, Australia"),
        (r"\bQueensland\b|\(Qld\)", "Queensland, Australia"),
        (r"\bWestern Australia\b|\(WA\)", "Western Australia, Australia"),
        (r"\bSouth Australia\b|\(SA\)", "South Australia, Australia"),
        (r"\bTasmania\b|\(Tas\)", "Tasmania, Australia"),
        (
            r"\bAustralian Capital Territory\b|\(ACT\)",
            "Australian Capital Territory, Australia",
        ),
        (r"\bNorthern Territory\b|\(NT\)", "Northern Territory, Australia"),
    ]
    hits: dict[str, list[int]] = {}
    for page_number, line in page_lines(pages):
        for pattern, value in state_rules:
            if re.search(pattern, line, re.IGNORECASE):
                hits.setdefault(value, []).append(page_number)
    if hits:
        value, page_numbers = max(hits.items(), key=lambda item: len(item[1]))
        occurrences = len(page_numbers)
        score = 0.72 if occurrences == 1 else 0.84 if occurrences == 2 else 0.93
        field = metadata_field(
            value,
            page_numbers[0],
            "jurisdiction_keyword_rule",
            score,
        )
        field["corroboration"] = f"jurisdiction keyword matched {occurrences} time(s)"
        return field
    return metadata_field(None, None, "not_found", 0.0)


def extract_citations(pages: list[dict[str, Any]]) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(value: str, page_number: int, kind: str) -> None:
        cleaned = re.sub(r"\s+", " ", value).strip(" .;,")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            citations.append(
                {
                    "value": cleaned,
                    "source_page": page_number,
                    "type": kind,
                }
            )

    for page_number, line in page_lines(pages):
        for match in re.finditer(
            r"\bISBN\s*:?[ \t]*"
            r"((?:97[89][ \t-]*)?[0-9Xx](?:[0-9Xx \t-]{8,20}[0-9Xx]))",
            line,
            re.IGNORECASE,
        ):
            add(f"ISBN {match.group(1).strip()}", page_number, "isbn")

        series = re.search(
            r"\bSeries\s*:\s*"
            r"(Report\s*\(Victorian Law Reform Commission\)(?:\s+\d+)?)",
            line,
            re.IGNORECASE,
        )
        if series:
            add(f"Series: {series.group(1)}", page_number, "series")

        for match in re.finditer(
            r"\b[A-Z][A-Za-z'’&-]*(?:[ \t]+[A-Z][A-Za-z'’&-]*)*"
            r"[ \t]+Act[ \t]+(?:19|20)\d{2}(?:[ \t]+\([A-Za-z]{2,4}\))?",
            line,
        ):
            add(match.group(0), page_number, "legislation")

        for match in re.finditer(
            r"\b[A-Z][A-Za-z'’.-]+[ \t]+v[ \t]+[A-Z][A-Za-z'’.-]+"
            r"(?:[ \t]+\[(?:19|20)\d{2}\][ \t]+"
            r"[A-Z0-9][A-Za-z0-9 ]{1,20}[ \t]+\d+)?",
            line,
        ):
            add(match.group(0), page_number, "case")

    kinds = {citation["type"] for citation in citations}
    if citations:
        score = min(
            0.95,
            0.55
            + 0.06 * min(len(citations), 4)
            + (0.08 if kinds & {"isbn", "series"} else 0.0)
            + 0.04 * max(0, len(kinds) - 1),
        )
    else:
        score = 0.0
    field = {
        "value": citations[:50],
        "source_page": citations[0]["source_page"] if citations else None,
        "method": "line_bounded_citation_rules",
        "confidence": round(score, 2),
    }
    if citations:
        field["corroboration"] = (
            f"{len(citations)} citation(s) across {len(kinds)} type(s): "
            + ", ".join(sorted(kinds))
        )
    return field


def _band(score: float, settings: Settings) -> str:
    if score >= settings.high_confidence_threshold:
        return "high"
    if score >= settings.medium_confidence_threshold:
        return "med"
    return "low"


def _display_value(field: dict[str, Any]) -> str:
    value = field.get("value")
    if isinstance(value, list):
        return "; ".join(
            str(item.get("value") if isinstance(item, dict) else item).strip()
            for item in value
            if str(item.get("value") if isinstance(item, dict) else item).strip()
        )
    return str(value or "").strip()


def _payload(
    fields: dict[str, dict[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    metadata = {name: _display_value(field) for name, field in fields.items()}
    field_info: dict[str, Any] = {}
    for name, field in fields.items():
        value = metadata[name]
        score = float(field.get("confidence", 0.0))
        page = int(field.get("source_page") or FIRST_PAGE)
        method = str(field.get("method") or "not_found")
        field_info[name] = {
            "band": _band(score, settings),
            "score": score,
            "page": page,
            "evidence": (
                f"Rule-based extraction matched “{value}”."
                if value
                else "No value matched the configured metadata rules."
            ),
            "source": (
                f"Docling text · page {page} · {method}"
                if field.get("source_page")
                else f"Docling text · pages {FIRST_PAGE}–{LAST_PAGE} · {method}"
            ),
        }
    return {"metadata": metadata, "fields": field_info}


def empty_metadata_payload(settings: Settings) -> dict[str, Any]:
    missing = metadata_field(None, None, "not_found", 0.0)
    return _payload(
        {
            "title": missing,
            "publisher": missing,
            "published_date": missing,
            "jurisdiction": missing,
            "citations": missing,
        },
        settings,
    )


def extract_metadata_from_docling(
    document: dict[str, Any],
    pdf_path: Path,
    settings: Settings,
) -> dict[str, Any]:
    pages = pages_from_docling(document)
    if not pages:
        return empty_metadata_payload(settings)
    return _payload(
        {
            "title": extract_title(pages, pdf_path),
            "publisher": extract_publisher(pages),
            "published_date": extract_date(pages, pdf_path),
            "jurisdiction": extract_jurisdiction(pages),
            "citations": extract_citations(pages),
        },
        settings,
    )
