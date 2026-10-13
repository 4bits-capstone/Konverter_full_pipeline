from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Callable, Iterable
from typing import Any

FIRST_PAGE = 1
LAST_PAGE = 8
# A runner-up title within this many rule points of the winner is close
# enough that a reviewer should pick between them.
TITLE_CONFLICT_MARGIN = 1.0
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
        if (item.get("meta") or {}).get("konverter_exclude_from_output"):
            continue
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


FILENAME_METHODS = {"filename_fallback", "filename_year_fallback"}


def flag(code: str, message: str, *, review: bool = True) -> dict[str, Any]:
    """A human-readable note about how a rule reached (or failed to reach) a value.

    ``review`` flags mean a person has to check the field before approval;
    the rest are informational context shown next to the value.
    """
    return {
        "code": code,
        "severity": "review" if review else "info",
        "message": message,
    }


def metadata_field(
    value: Any,
    source_page: int | None,
    method: str,
    flags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    field_flags = list(flags or [])
    if value in (None, "", []):
        field_flags.insert(
            0,
            flag(
                "missing",
                f"No value matched the metadata rules in pages {FIRST_PAGE}–{LAST_PAGE}.",
            ),
        )
    elif method in FILENAME_METHODS:
        field_flags.insert(
            0,
            flag(
                "fallback_source",
                "Taken from the file name because nothing matched in the document text.",
            ),
        )
    return {
        "value": value,
        "source_page": source_page,
        "method": method,
        "flags": field_flags,
    }


def _page_label(page: int | None) -> str:
    return f"page {page}" if page else "an unknown page"


def _distinct_titles(first: str, second: str) -> bool:
    a, b = first.casefold(), second.casefold()
    return a != b and a not in b and b not in a


def normalise_title(title: Any) -> str:
    value = clean_line(title)
    value = re.sub(
        r"^.*?(?:https?://|www\.)\S+\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^National Library of Australia(?:\s+Cataloguing-in-Publication)?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
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
    if (
        value.isupper()
        or re.search(r"[a-z][A-Z]\b", value)
        or (len(value.split()) <= 12 and value == value.capitalize())
    ):
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


def _pdf_metadata(pdf_path: Path) -> dict[str, str]:
    try:
        import fitz

        with fitz.open(pdf_path) as document:
            return {
                str(key): clean_line(value)
                for key, value in (document.metadata or {}).items()
                if clean_line(value)
            }
    except Exception:
        return {}


def _valid_title_candidate(value: str) -> bool:
    words = value.split()
    if not (1 <= len(words) <= 18 and 5 <= len(value) <= 180):
        return False
    return not bool(
        re.search(
            r"(?:microsoft\s+word|\.doc\b|@|www\.|isbn|copyright|"
            r"\bthis report\b|\breflects the law\b|\bestablished under\b|"
            r"\bfinal report view\b)",
            value,
            re.IGNORECASE,
        )
    )


def extract_title(
    pages: list[dict[str, Any]],
    pdf_path: Path,
) -> dict[str, Any]:
    lines = list(page_lines(pages))
    candidates: list[dict[str, Any]] = []

    def add(
        value: Any,
        page_number: int | None,
        method: str,
        score: float,
        position: int = 999,
    ) -> None:
        title = normalise_title(value)
        if _valid_title_candidate(title):
            candidates.append(
                {
                    "title": title,
                    "page": page_number,
                    "method": method,
                    "score": score,
                    "position": position,
                }
            )

    pdf_title = _pdf_metadata(pdf_path).get("title", "")
    if pdf_title:
        add(pdf_title, 1, "pdf_metadata_title", 12.5, 0)

    for position, (page_number, line) in enumerate(lines[:120]):
        catalogued = re.match(
            r"(?:title\s*:\s*)?(.+?)(?::\s*(?:final\s+)?report)?\s*/\s*"
            r"Victorian Law Reform Commission\b",
            line,
            re.IGNORECASE,
        )
        if catalogued:
            add(catalogued.group(1), page_number, "cataloguing_title_rule", 16, position)

        labelled = re.match(r"title\s*:\s*(.+)$", line, re.IGNORECASE)
        if labelled:
            add(labelled.group(1), page_number, "labelled_title_rule", 15, position)

        cip_line = re.sub(
            r"^National Library of Australia(?:\s+Cataloguing-in-Publication)?\s*",
            "",
            line,
            flags=re.IGNORECASE,
        )
        report_match = re.fullmatch(
            r"(.+?)\s*:\s*(?:final\s+)?report\.?",
            cip_line,
            re.IGNORECASE,
        )
        if report_match:
            add(report_match.group(1), page_number, "cataloguing_report_title_rule", 15, position)
        else:
            trailing_report = re.fullmatch(
                r"(.+?)\s+(?:final\s+)?report\.?",
                cip_line,
                re.IGNORECASE,
            )
            if trailing_report:
                add(trailing_report.group(1), page_number, "cover_report_title_rule", 11.5, position)

        contact_title = re.search(
            r"(?:https?://|www\.)\S+\s+([A-Z][A-Z\s'’&-]{5,})$",
            line,
        )
        if contact_title:
            add(contact_title.group(1), page_number, "cover_title_after_contact_rule", 13, position)

        letters = [character for character in line if character.isalpha()]
        uppercase_ratio = (
            sum(character.isupper() for character in letters) / len(letters)
            if letters
            else 0
        )
        if uppercase_ratio >= 0.86 and 2 <= len(line.split()) <= 16:
            add(line, page_number, "cover_uppercase_title_rule", 10.5, position)

    if candidates:
        for candidate in candidates:
            key = candidate["title"].casefold()
            matched_pages = {
                page_number
                for page_number, line in lines
                if key and key in normalise_title(line).casefold()
            }
            candidate["matches"] = len(matched_pages)
            candidate["score"] += min(3, len(matched_pages)) * 0.7
            if candidate["page"] == 1:
                candidate["score"] += 0.5
            candidate["score"] -= min(candidate["position"], 60) * 0.005

        ranked = sorted(candidates, key=lambda candidate: candidate["score"], reverse=True)
        best = ranked[0]
        flags: list[dict[str, Any]] = []
        rival = next(
            (
                candidate
                for candidate in ranked[1:]
                if _distinct_titles(candidate["title"], best["title"])
                and best["score"] - candidate["score"] <= TITLE_CONFLICT_MARGIN
            ),
            None,
        )
        if rival is not None:
            flags.append(
                flag(
                    "rule_conflict",
                    f"Another rule found a different title on {_page_label(rival['page'])}: "
                    f"“{rival['title']}”.",
                )
            )
        if best["method"] == "pdf_metadata_title" and best["matches"] == 0:
            flags.append(
                flag(
                    "unconfirmed_source",
                    "Taken from the PDF file properties and not found in the document text.",
                )
            )
        return metadata_field(best["title"], best["page"], best["method"], flags)

    fallback = _filename_title(pdf_path)
    return metadata_field(fallback or None, None, "filename_fallback")


def extract_publisher(
    pages: list[dict[str, Any]],
    pdf_path: Path | None = None,
) -> dict[str, Any]:
    published_by: list[tuple[str, int]] = []
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
                published_by.append((publisher, page_number))

    if published_by:
        publisher, page_number = published_by[0]
        flags: list[dict[str, Any]] = []
        rival = next(
            (
                (other, other_page)
                for other, other_page in published_by[1:]
                if _distinct_titles(other, publisher)
            ),
            None,
        )
        if rival is not None:
            flags.append(
                flag(
                    "rule_conflict",
                    f"A second “published by” line on {_page_label(rival[1])} "
                    f"names “{rival[0]}”.",
                )
            )
        return metadata_field(publisher, page_number, "published_by_rule", flags)

    organisation_pages = [
        page_number
        for page_number, line in page_lines(pages)
        if re.search(r"\bVictorian Law Reform Commission\b", line, re.IGNORECASE)
    ]
    if organisation_pages:
        occurrences = len(organisation_pages)
        return metadata_field(
            "Victorian Law Reform Commission",
            organisation_pages[0],
            "organisation_name_rule",
            [
                flag(
                    "inferred",
                    "No “published by” line was found; inferred from the "
                    f"organisation name ({occurrences} mention(s)).",
                    review=occurrences == 1,
                )
            ],
        )

    if pdf_path is not None:
        author = _pdf_metadata(pdf_path).get("author", "")
        if re.search(r"\b(?:commission|department|ministry|government)\b", author, re.IGNORECASE):
            return metadata_field(
                author,
                1,
                "pdf_metadata_author_rule",
                [
                    flag(
                        "unconfirmed_source",
                        "Taken from the PDF author property, not the document text.",
                    )
                ],
            )

    return metadata_field(None, None, "not_found")


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


DATE_RULE_LABELS = {
    "cover_report_date_rule": "the report line",
    "cover_date_rule": "a cover date line",
    "copyright_date_rule": "the copyright line",
    "publication_date_rule": "a “published” line",
    "copyright_year_rule": "the copyright year",
    "pdf_metadata_subject_date_rule": "the PDF subject property",
}


def _date_parts(value: str) -> tuple[str, str | None]:
    """Split a normalised YYYY[-MM[-DD]] date into its year and optional month."""
    parts = value.split("-")
    return parts[0], parts[1] if len(parts) > 1 else None


def _dates_disagree(first: str, second: str) -> bool:
    first_year, first_month = _date_parts(first)
    second_year, second_month = _date_parts(second)
    if first_year != second_year:
        return True
    return bool(first_month and second_month and first_month != second_month)


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
        ),
        (
            rf"^((?:\d{{1,2}}\s+)?{MONTHS}\s+\d{{4}})$",
            "cover_date_rule",
        ),
        (
            rf"©\s*((?:\d{{1,2}}\s+)?{MONTHS}\s+\d{{4}})\b",
            "copyright_date_rule",
        ),
        (
            rf"\bpublished[^\n]*?\b((?:\d{{1,2}}\s+)?{MONTHS}\s+\d{{4}})\b",
            "publication_date_rule",
        ),
        (r"©[^\n]*?\b((?:19|20)\d{2})\b", "copyright_year_rule"),
    ]
    # Run every rule (first hit each, in precedence order) rather than
    # stopping at the first match, so disagreeing rules can be surfaced.
    matches: list[tuple[str, int, str]] = []
    for pattern, method in patterns:
        for page_number, line in lines:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                matches.append((_normalise_date(match.group(1)), page_number, method))
                break

    # PDF properties rank below the dated text rules but above a bare
    # copyright year, matching the original precedence.
    subject = _pdf_metadata(pdf_path).get("subject", "")
    subject_match = re.search(
        rf"\b((?:\d{{1,2}}\s+)?{MONTHS}\s+\d{{4}})\b",
        subject,
        re.IGNORECASE,
    )
    if subject_match:
        position = next(
            (
                index
                for index, candidate in enumerate(matches)
                if candidate[2] == "copyright_year_rule"
            ),
            len(matches),
        )
        matches.insert(
            position,
            (_normalise_date(subject_match.group(1)), 1, "pdf_metadata_subject_date_rule"),
        )

    if matches:
        value, page_number, method = matches[0]
        flags: list[dict[str, Any]] = []
        rival = next(
            (
                candidate
                for candidate in matches[1:]
                if _dates_disagree(value, candidate[0])
            ),
            None,
        )
        if rival is not None:
            flags.append(
                flag(
                    "rule_conflict",
                    f"{DATE_RULE_LABELS[method][0].upper()}{DATE_RULE_LABELS[method][1:]} "
                    f"({_page_label(page_number)}) gives {value}, but "
                    f"{DATE_RULE_LABELS[rival[2]]} ({_page_label(rival[1])}) "
                    f"gives {rival[0]}.",
                )
            )
        if method == "pdf_metadata_subject_date_rule":
            flags.append(
                flag(
                    "unconfirmed_source",
                    "Taken from the PDF subject property, not the document text.",
                )
            )
        if method == "copyright_year_rule":
            flags.append(
                flag(
                    "partial_value",
                    "Only a year was found; add the month or day if the document gives one.",
                )
            )
        return metadata_field(value, page_number, method, flags)

    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", pdf_path.stem)
    if match:
        return metadata_field(match.group(1), None, "filename_year_fallback")
    return metadata_field(None, None, "not_found")


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
        ranked = sorted(hits.items(), key=lambda item: len(item[1]), reverse=True)
        value, page_numbers = ranked[0]
        occurrences = len(page_numbers)
        flags: list[dict[str, Any]] = []
        if occurrences == 1:
            flags.append(
                flag(
                    "single_match",
                    f"The jurisdiction keyword appears only once ({_page_label(page_numbers[0])}).",
                )
            )
        if len(ranked) > 1:
            rival, rival_pages = ranked[1]
            # A report routinely mentions other states in passing; only a
            # rival with at least half as many mentions is a real conflict.
            close = len(rival_pages) * 2 >= occurrences
            flags.append(
                flag(
                    "rule_conflict" if close else "other_values",
                    f"{rival} is also mentioned {len(rival_pages)} time(s), "
                    f"against {occurrences} for {value}.",
                    review=close,
                )
            )
        return metadata_field(
            value,
            page_numbers[0],
            "jurisdiction_keyword_rule",
            flags,
        )
    return metadata_field(None, None, "not_found")


def extract_citations(pages: list[dict[str, Any]]) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(value: str, page_number: int, kind: str) -> None:
        cleaned = re.sub(r"\s+", " ", value).strip(" .;,")
        if kind == "legislation":
            cleaned = re.sub(r"^The\s+", "", cleaned, flags=re.IGNORECASE)
        key = re.sub(r"[^a-z0-9]", "", cleaned.casefold())
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
    flags: list[dict[str, Any]] = []
    if citations and not kinds & {"isbn", "series"}:
        flags.append(
            flag(
                "uncorroborated",
                "No ISBN or series line was found; confirm these are the "
                "document's own citations, not passing references.",
            )
        )
    return metadata_field(
        citations[:50],
        citations[0]["source_page"] if citations else None,
        "line_bounded_citation_rules",
        flags,
    )


def _display_value(field: dict[str, Any]) -> str:
    value = field.get("value")
    if isinstance(value, list):
        return "; ".join(
            str(item.get("value") if isinstance(item, dict) else item).strip()
            for item in value
            if str(item.get("value") if isinstance(item, dict) else item).strip()
        )
    return str(value or "").strip()


def _payload(fields: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata = {name: _display_value(field) for name, field in fields.items()}
    field_info: dict[str, Any] = {}
    for name, field in fields.items():
        value = metadata[name]
        page = int(field.get("source_page") or FIRST_PAGE)
        method = str(field.get("method") or "not_found")
        flags = list(field.get("flags") or [])
        field_info[name] = {
            "flags": flags,
            "review_needed": any(item["severity"] == "review" for item in flags),
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


def empty_metadata_payload() -> dict[str, Any]:
    missing = metadata_field(None, None, "not_found")
    return _payload(
        {
            "title": missing,
            "publisher": missing,
            "published_date": missing,
            "jurisdiction": missing,
            "citations": missing,
        }
    )


def extract_metadata_from_docling(
    document: dict[str, Any],
    pdf_path: Path,
) -> dict[str, Any]:
    pages = pages_from_docling(document)
    if not pages:
        return empty_metadata_payload()
    return _payload(
        {
            "title": extract_title(pages, pdf_path),
            "publisher": extract_publisher(pages, pdf_path),
            "published_date": extract_date(pages, pdf_path),
            "jurisdiction": extract_jurisdiction(pages),
            "citations": extract_citations(pages),
        }
    )
