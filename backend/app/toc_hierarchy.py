"""Printed table-of-contents extraction and Konverter heading assignment.

Docling's native heading hierarchy is the fallback signal for body headings.  This
module supplies the publication contract that Docling cannot infer on its own:

* the printed contents pages are authoritative for H1/H2 navigation;
* front matter and back matter listed there are treated like any other H1;
* chapter/part entries are H1 and their listed descendants are H2;
* printed contents rows are removed from accessible output; and
* a missing Docling heading is restored from the printed contents entry.

The parser is layout based rather than tied to a VLRC report title.  It supports
page numbers before a title, after a title, or joined by dot leaders, including
two-column and mixed contents/body pages.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import pymupdf


_ROMAN_TOKEN = (
    r"(?=[ivxlcdm]{1,12}(?:\b|$))"
    r"m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"
)
_PAGE_TOKEN = rf"(?:\d{{1,4}}|{_ROMAN_TOKEN})"
_PAGE_ONLY = re.compile(rf"^{_PAGE_TOKEN}$", re.IGNORECASE)
_LEADER_ENTRY = re.compile(
    rf"^(?P<title>.+?)\s*\.{{2,}}\s*(?P<page>{_PAGE_TOKEN})$",
    re.IGNORECASE,
)
_PREFIX_ENTRY = re.compile(
    rf"^(?P<page>{_PAGE_TOKEN})[\s\u2002-\u200b\u202f]+(?P<title>\D.+)$",
    re.IGNORECASE,
)
_SUFFIX_ENTRY = re.compile(
    rf"^(?P<title>.+?)[\s\u2002-\u200b\u202f]{{2,}}(?P<page>{_PAGE_TOKEN})$",
    re.IGNORECASE,
)
_CONTENTS_HEADING = re.compile(
    r"^(?:table\s+of\s+)?contents$", re.IGNORECASE
)
_TOP_LEVEL = re.compile(
    r"^(?:"
    r"(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b|"
    r"\d+[.)]\s+.+|"
    r"preface|foreword|"
    r"terms?\s+of\s+reference|scope\s+of\s+(?:the\s+)?report|"
    r"glossary(?:\s+of\b.*)?|abbreviations?|acronyms?|"
    r"executive\s+summary|recommendations?|contributors?|"
    r"acknowledg(?:e)?ments?|appendices|bibliography|references|index|"
    r"list\s+of\s+(?:figures|tables|recommendations)|"
    r"about\s+the\s+commission"
    r")\s*(?::.*)?$",
    re.IGNORECASE,
)
_APPENDIX_ENTRY = re.compile(
    r"^appendix\s+(?:[a-z]|\d+|[ivxlcdm]+)\b", re.IGNORECASE
)
_UNPAGED_TOP_LEVEL = re.compile(
    r"^(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b.*|appendices)$",
    re.IGNORECASE,
)
_ALWAYS_TOP_LEVEL = re.compile(
    r"^(?:appendices|glossary(?:\s+of\b.*)?|bibliography|references|index)$",
    re.IGNORECASE,
)
_NUMBERING_PREFIX = re.compile(
    r"^\s*(?:(?:chapter|part|section)\s+)?"
    r"(?:\d+(?:\.\d+)*|[ivxlcdm]+|[a-z])"
    r"(?:[.):\-–—]|\s)+",
    re.IGNORECASE,
)
_INTERNAL_CONTENTS = re.compile(r"^(?:chapter\s+)?contents$", re.IGNORECASE)
_GENERIC_PANEL_HEADING = re.compile(
    r"^(?:recommendations?|case\s+stud(?:y|ies)(?:\s+\d+)?|example|note)$",
    re.IGNORECASE,
)
_NUMBERED_BODY_HEADING = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+){1,4})[.)]?\s+(?P<title>\S.+)$"
)
_NON_BODY_HEADING = re.compile(
    r"^(?:"
    r"(?:figure|table)\s+\d+\s*[:.]|"
    r"(?:isbn|issn|©|copyright)\b|"
    r"(?:published|printed|ordered)\s+by\b|"
    r"report\s+(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b"
    r")",
    re.IGNORECASE,
)
_CHAPTER_MARKER = re.compile(
    r"^chapter\s+(?P<number>\d{1,3}|[ivxlcdm]+)\s*(?:[:.\-–—]\s*(?P<title>.+))?$",
    re.IGNORECASE,
)
_NUMBERED_CHAPTER_TITLE = re.compile(
    r"^(?P<number>\d{1,3})\s*[.)]\s*(?P<title>\S.+)$"
)


@dataclass(frozen=True)
class TextLine:
    text: str
    bbox: tuple[float, float, float, float]
    size: float
    prominent: bool = False

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class TocEntry:
    title: str
    level: int
    printed_page: str | None
    toc_page: int
    bbox: tuple[float, float, float, float]
    indent: float = 0.0
    sequence: int = 0
    target_page: int | None = None
    target_y: float | None = None
    matched_ref: str | None = None
    prominent: bool = False


@dataclass
class TocOutline:
    entries: list[TocEntry] = field(default_factory=list)
    toc_pages: set[int] = field(default_factory=set)
    regions: dict[int, list[tuple[float, float, float, float]]] = field(
        default_factory=dict
    )
    warnings: list[str] = field(default_factory=list)

    @property
    def first_page(self) -> int | None:
        return min(self.toc_pages) if self.toc_pages else None

    @property
    def last_page(self) -> int | None:
        return max(self.toc_pages) if self.toc_pages else None


@dataclass(frozen=True)
class ChapterPage:
    """A chapter boundary independently observed on a body title page."""

    number: int
    title: str
    page: int
    top: float
    local_entries: tuple[TocEntry, ...] = ()


def _clean_text(value: str) -> str:
    value = value.replace("\u00ad", "").replace("\x07", " ")
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    value = re.sub(r"\s+", " ", value).strip(" \t.·•")
    return value


def _match_key(value: str, *, strip_numbering: bool = False) -> str:
    value = _clean_text(value).casefold().replace("&", " and ")
    value = value.replace("’", "'").replace("‘", "'")
    if strip_numbering:
        value = _NUMBERING_PREFIX.sub("", value)
    value = re.sub(r"\bchapter\s+(\d+|[ivxlcdm]+)\b", " ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _similarity(first: str, second: str) -> float:
    variants_first = {_match_key(first), _match_key(first, strip_numbering=True)}
    variants_second = {_match_key(second), _match_key(second, strip_numbering=True)}
    variants_first.discard("")
    variants_second.discard("")
    best = 0.0
    for left in variants_first:
        for right in variants_second:
            if left == right:
                return 1.0
            ratio = SequenceMatcher(None, left, right).ratio()
            left_tokens = set(left.split())
            right_tokens = set(right.split())
            overlap = len(left_tokens & right_tokens) / max(
                1, len(left_tokens | right_tokens)
            )
            best = max(best, ratio, overlap * 0.95)
    return best


def _union_boxes(
    values: Iterable[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    boxes = list(values)
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _page_lines(page: pymupdf.Page) -> list[TextLine]:
    output: list[TextLine] = []
    payload = page.get_text("dict", sort=True)
    for block in payload.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = _clean_text("".join(str(span.get("text", "")) for span in spans))
            if not text:
                continue
            bbox = tuple(float(value) for value in line.get("bbox", (0, 0, 0, 0)))
            size = max((float(span.get("size", 0)) for span in spans), default=0.0)
            prominent = any(
                int(span.get("flags", 0)) & 16
                or any(
                    marker in str(span.get("font", "")).casefold()
                    for marker in ("bold", "black", "heavy")
                )
                for span in spans
                if str(span.get("text", "")).strip()
            )
            output.append(
                TextLine(text=text, bbox=bbox, size=size, prominent=prominent)
            )
    return output


def _cluster_positions(values: list[float], tolerance: float) -> list[float]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or value - median(clusters[-1]) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [float(median(cluster)) for cluster in clusters]


def _inline_entry(line: TextLine) -> tuple[str, str, tuple[float, float, float, float]] | None:
    for pattern in (_LEADER_ENTRY, _PREFIX_ENTRY, _SUFFIX_ENTRY):
        match = pattern.match(line.text)
        if match:
            title = _clean_text(match.group("title"))
            if title and len(title) <= 300:
                return title, match.group("page"), line.bbox
    return None


def _entries_from_page(page: pymupdf.Page, page_number: int) -> tuple[list[TocEntry], list[TextLine]]:
    lines = _page_lines(page)
    height = float(page.rect.height)
    usable = [line for line in lines if 42 <= line.center_y <= height - 45]
    entries: list[tuple[str, str, tuple[float, float, float, float], TextLine]] = []
    used_title_lines: set[int] = set()
    used_number_lines: set[int] = set()

    for index, line in enumerate(usable):
        parsed = _inline_entry(line)
        if parsed is None:
            continue
        title, printed_page, bbox = parsed
        title_parts = [line]
        # A wrapped TOC row commonly puts the page marker on its final line.
        # Recover up to two preceding fragments before classifying the row.
        for _ in range(4):
            previous_candidates: list[tuple[float, int, TextLine]] = []
            for candidate_index, previous in enumerate(usable):
                if candidate_index in used_title_lines or candidate_index >= index:
                    continue
                gap = title_parts[0].y0 - previous.y1
                if not (-2.0 <= gap <= 3.5):
                    continue
                if abs(previous.x0 - line.x0) > 60:
                    continue
                if (
                    _PAGE_ONLY.fullmatch(previous.text)
                    or _CONTENTS_HEADING.fullmatch(previous.text)
                    or _inline_entry(previous) is not None
                ):
                    continue
                # Prefer attaching an in-between fragment to the entry above
                # when it is visibly closer.  This prevents a wrapped chapter
                # suffix (for example "Resolution") being stolen by the next
                # numbered child row.
                structural_prefix = bool(
                    _UNPAGED_TOP_LEVEL.fullmatch(previous.text)
                    or re.match(r"^\d+[.)]\s+", previous.text)
                )
                if not structural_prefix and any(
                    abs(existing_line.x0 - previous.x0) <= 60
                    and -2.0 <= previous.y0 - existing_bbox[3] <= gap
                    for _, _, existing_bbox, existing_line in entries
                ):
                    continue
                previous_candidates.append((abs(gap), candidate_index, previous))
            if not previous_candidates:
                break
            _, candidate_index, previous = min(previous_candidates)
            title_parts.insert(0, previous)
            used_title_lines.add(candidate_index)
        if len(title_parts) > 1:
            title = _clean_text(
                " ".join([part.text for part in title_parts[:-1]] + [title])
            )
            bbox = _union_boxes(part.bbox for part in title_parts)
            line = title_parts[0]
        entries.append((title, printed_page, bbox, line))
        used_title_lines.add(index)

    number_indices = [
        index
        for index, line in enumerate(usable)
        if index not in used_title_lines and _PAGE_ONLY.fullmatch(line.text)
    ]
    if number_indices:
        number_x = [usable[index].x0 for index in number_indices]
        tolerance = max(16.0, float(page.rect.width) * 0.08)
        clusters = _cluster_positions(number_x, tolerance)
        clusters = [
            cluster
            for cluster in clusters
            if sum(abs(value - cluster) <= tolerance for value in number_x) >= 3
        ]
        if not clusters:
            clusters = _cluster_positions(number_x, tolerance)
        # VLRC templates consistently place all page numbers either before or
        # after their titles.  The first marker position identifies the layout.
        numbers_before_titles = min(clusters) < float(page.rect.width) * 0.28
        for number_index in number_indices:
            number_line = usable[number_index]
            cluster_index = min(
                range(len(clusters)), key=lambda value: abs(clusters[value] - number_line.x0)
            )
            previous_marker = clusters[cluster_index - 1] if cluster_index else 0.0
            following_marker = (
                clusters[cluster_index + 1]
                if cluster_index + 1 < len(clusters)
                else float(page.rect.width)
            )
            candidates: list[tuple[float, int, TextLine]] = []
            for title_index, title_line in enumerate(usable):
                if title_index in used_title_lines or title_index in number_indices:
                    continue
                if _CONTENTS_HEADING.fullmatch(title_line.text):
                    continue
                vertical = abs(title_line.center_y - number_line.center_y)
                if vertical > max(3.5, (number_line.y1 - number_line.y0) * 0.48):
                    continue
                if numbers_before_titles:
                    valid_horizontal = (
                        number_line.x1 - 3 <= title_line.x0 <= following_marker - 8
                    )
                    distance = abs(title_line.x0 - number_line.x1)
                else:
                    valid_horizontal = (
                        previous_marker + 8 <= title_line.x0
                        and title_line.x1 <= number_line.x0 + 3
                    )
                    distance = abs(number_line.x0 - title_line.x1)
                if valid_horizontal:
                    candidates.append((vertical * 20 + distance, title_index, title_line))
            if not candidates:
                continue
            _, title_index, title_line = min(candidates)
            used_title_lines.add(title_index)
            used_number_lines.add(number_index)

            title_parts = [title_line]
            # Recover wrapped title lines that precede the page-number row.
            for _ in range(4):
                previous_candidates: list[tuple[float, int, TextLine]] = []
                for candidate_index, previous in enumerate(usable):
                    if candidate_index in used_title_lines or candidate_index in number_indices:
                        continue
                    gap = title_parts[0].y0 - previous.y1
                    if not (-1.0 <= gap <= 2.0):
                        continue
                    if abs(previous.x0 - title_line.x0) > 60:
                        continue
                    previous_candidates.append((abs(gap), candidate_index, previous))
                if not previous_candidates:
                    break
                _, candidate_index, previous = min(previous_candidates)
                title_parts.insert(0, previous)
                used_title_lines.add(candidate_index)

            title = _clean_text(" ".join(part.text for part in title_parts))
            if title and len(title) <= 300:
                entries.append(
                    (
                        title,
                        number_line.text,
                        _union_boxes([part.bbox for part in title_parts] + [number_line.bbox]),
                        title_parts[0],
                    )
                )

    # Some designed TOCs omit a page number from the chapter row and place the
    # first number on its first child.  Retain those explicit structural rows;
    # their body target is resolved later by bookmark/title matching.
    for index, line in enumerate(usable):
        if index in used_title_lines or index in used_number_lines:
            continue
        if not _UNPAGED_TOP_LEVEL.fullmatch(line.text):
            continue
        title_parts = [line]
        for _ in range(2):
            following_candidates: list[tuple[float, int, TextLine]] = []
            for candidate_index, following in enumerate(usable):
                if candidate_index in used_title_lines or candidate_index in number_indices:
                    continue
                gap = following.y0 - title_parts[-1].y1
                if not (-1.0 <= gap <= max(5.0, following.y1 - following.y0) * 0.55):
                    continue
                if (
                    abs(following.x0 - line.x0) > 22
                    or _PAGE_ONLY.fullmatch(following.text)
                    or _inline_entry(following) is not None
                    or re.search(rf"\s{_PAGE_TOKEN}$", following.text, re.IGNORECASE)
                ):
                    continue
                following_candidates.append((abs(gap), candidate_index, following))
            if not following_candidates:
                break
            _, candidate_index, following = min(following_candidates)
            title_parts.append(following)
            used_title_lines.add(candidate_index)
        title = _clean_text(" ".join(part.text for part in title_parts))
        entries.append((title, "", _union_boxes(part.bbox for part in title_parts), line))

    expanded_entries: list[
        tuple[str, str, tuple[float, float, float, float], TextLine]
    ] = []
    for title, printed_page, bbox, title_line in entries:
        parts = [title]
        boxes = [bbox]
        current_bottom = bbox[3]
        for _ in range(2):
            continuations: list[tuple[float, int, TextLine]] = []
            for index, line in enumerate(usable):
                if index in used_title_lines or index in used_number_lines:
                    continue
                gap = line.y0 - current_bottom
                if not (-2.0 <= gap <= max(5.0, line.y1 - line.y0) * 0.55):
                    continue
                if abs(line.x0 - title_line.x0) > 28:
                    continue
                if (
                    _PAGE_ONLY.fullmatch(line.text)
                    or _CONTENTS_HEADING.fullmatch(line.text)
                    or _inline_entry(line) is not None
                    or re.search(rf"\s{_PAGE_TOKEN}$", line.text, re.IGNORECASE)
                    or _UNPAGED_TOP_LEVEL.fullmatch(line.text)
                ):
                    continue
                continuations.append((abs(gap), index, line))
            if not continuations:
                break
            _, index, line = min(continuations)
            used_title_lines.add(index)
            parts.append(line.text)
            boxes.append(line.bbox)
            current_bottom = line.y1
        expanded_entries.append(
            (_clean_text(" ".join(parts)), printed_page, _union_boxes(boxes), title_line)
        )
    entries = expanded_entries

    output: list[TocEntry] = []
    seen: set[tuple[str, str, int, int]] = set()
    entry_columns = _cluster_positions(
        [value[2][0] for value in entries],
        max(42.0, float(page.rect.width) * 0.2),
    )
    ordered_entries = sorted(
        entries,
        key=lambda value: (
            min(
                range(len(entry_columns)),
                key=lambda index: abs(entry_columns[index] - value[2][0]),
            )
            if entry_columns
            else 0,
            value[2][1],
            value[2][0],
        ),
    )
    for title, printed_page, bbox, title_line in ordered_entries:
        key = (_match_key(title), printed_page.casefold(), round(bbox[0]), round(bbox[1]))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        output.append(
            TocEntry(
                title=title,
                level=1 if _TOP_LEVEL.match(title) else 2,
                printed_page=printed_page or None,
                toc_page=page_number,
                bbox=bbox,
                indent=title_line.x0,
                prominent=title_line.prominent,
            )
        )
    return output, lines


def _looks_like_contents_page(
    entries: list[TocEntry], lines: list[TextLine], *, is_continuation: bool
) -> bool:
    has_heading = any(_CONTENTS_HEADING.fullmatch(line.text) for line in lines)
    if has_heading and len(entries) >= 3:
        return True
    return is_continuation and len(entries) >= 5


def _normalise_outline_levels(entries: list[TocEntry]) -> list[TocEntry]:
    if not entries:
        return entries
    output: list[TocEntry] = []
    appendix_run = False
    has_appendices = any(
        _match_key(entry.title) in {"appendix", "appendices"} for entry in entries
    )
    body_started = False
    current_top_indent: float | None = None
    for entry in entries:
        if re.match(
            r"^(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b|\d+[.)]\s+.+)",
            entry.title,
            re.IGNORECASE,
        ):
            entry.level = 1
            body_started = True
            current_top_indent = entry.indent
        elif body_started and re.match(r"^recommendations?\b", entry.title, re.IGNORECASE):
            entry.level = 2
        elif (
            body_started
            and entry.level == 1
            and current_top_indent is not None
            and entry.indent > current_top_indent + 7
            and not _ALWAYS_TOP_LEVEL.fullmatch(entry.title)
        ):
            entry.level = 2
        if _APPENDIX_ENTRY.match(entry.title):
            if not has_appendices and not appendix_run:
                output.append(
                    TocEntry(
                        title="Appendices",
                        level=1,
                        printed_page=entry.printed_page,
                        toc_page=entry.toc_page,
                        bbox=entry.bbox,
                        indent=entry.indent,
                    )
                )
            appendix_run = True
            entry.level = 2
        elif entry.level == 1:
            appendix_run = False
        entry.level = 1 if entry.level == 1 else 2
        output.append(entry)
    for sequence, entry in enumerate(output):
        entry.sequence = sequence

    # A few older designed contents omit the literal "Chapter N" prefix from
    # one bold chapter row.  Repair only a numbered gap bounded by explicit
    # chapter rows, avoiding a general typography-to-heading rule.
    numbered: list[tuple[int, int]] = []
    for index, entry in enumerate(output):
        match = re.match(r"^chapter\s+(\d+)\b", entry.title, re.IGNORECASE)
        if match:
            numbered.append((index, int(match.group(1))))
    for (left_index, left_number), (right_index, right_number) in zip(
        numbered, numbered[1:]
    ):
        missing = right_number - left_number - 1
        if missing <= 0:
            continue
        candidates = [
            entry
            for entry in output[left_index + 1 : right_index]
            if entry.level == 2
            and entry.prominent
            and entry.printed_page
            and entry.printed_page.isdigit()
            and not re.match(
                r"^(?:recommendations?|introduction|summary|conclusion)",
                entry.title,
                re.IGNORECASE,
            )
        ]
        for offset, entry in enumerate(candidates[:missing], start=1):
            entry.level = 1
            entry.title = f"Chapter {left_number + offset}: {entry.title}"
    return output


def _bookmark_targets(document: pymupdf.Document) -> list[tuple[str, int]]:
    output: list[tuple[str, int]] = []
    try:
        for value in document.get_toc(simple=True):
            if len(value) >= 3 and int(value[2]) > 0:
                output.append((_clean_text(str(value[1])), int(value[2])))
    except Exception:
        return []
    return output


def _page_label_targets(document: pymupdf.Document) -> dict[str, list[int]]:
    output: dict[str, list[int]] = {}
    for index in range(len(document)):
        label = _clean_text(document[index].get_label())
        if label:
            output.setdefault(label.casefold(), []).append(index + 1)
    return output


def _locate_entry_targets(document: pymupdf.Document, outline: TocOutline) -> None:
    bookmarks = _bookmark_targets(document)
    labels = _page_label_targets(document)
    offsets: list[int] = []

    # Printed page labels are the most reliable destination signal.  In many
    # legal reports the bookmark tree also contains repeated short headings
    # such as "Introduction" and "Conclusion"; selecting the best bookmark
    # first can therefore move Chapter 1 near the end of the document.
    for entry in outline.entries:
        if entry.printed_page:
            labelled = labels.get(entry.printed_page.casefold(), [])
            labelled = [page for page in labelled if page > (outline.last_page or 0)]
            if labelled:
                entry.target_page = labelled[0]
        if (
            entry.target_page is not None
            and entry.printed_page
            and entry.printed_page.isdigit()
        ):
            offsets.append(entry.target_page - int(entry.printed_page))

    page_offset = int(round(median(offsets))) if offsets else None
    if page_offset is not None:
        for entry in outline.entries:
            if entry.target_page is None and entry.printed_page and entry.printed_page.isdigit():
                candidate = int(entry.printed_page) + page_offset
                if (outline.last_page or 0) < candidate <= len(document):
                    entry.target_page = candidate

    start_page = (outline.last_page or 0) + 1
    page_cache: dict[int, list[TextLine]] = {}
    if page_offset is None:
        anchors = [
            entry
            for entry in outline.entries
            if entry.level == 1
            and entry.printed_page
            and entry.printed_page.isdigit()
            and len(_match_key(entry.title).split()) >= 2
        ][:16]
        page_text_cache: dict[int, str] = {}

        def page_contains(page_number: int, entry: TocEntry) -> bool:
            lines = page_cache.setdefault(
                page_number, _page_lines(document[page_number - 1])
            )
            page_text = page_text_cache.setdefault(
                page_number, _match_key(" ".join(line.text for line in lines))
            )
            keys = {
                _match_key(entry.title),
                _match_key(entry.title, strip_numbering=True),
            }
            keys.discard("")
            return any(len(key) >= 8 and key in page_text for key in keys)

        # Search plausible physical/printed page offsets directly.  This is
        # much faster on long bookmark-free reports than fuzzy-comparing every
        # TOC entry against every line on every page.
        best_offset: int | None = None
        best_hits = 0
        for candidate_offset in range(-10, 81):
            hits = 0
            for entry in anchors:
                candidate_page = int(entry.printed_page or 0) + candidate_offset
                if not (start_page <= candidate_page <= len(document)):
                    continue
                if page_contains(candidate_page, entry):
                    hits += 1
            if hits > best_hits:
                best_hits = hits
                best_offset = candidate_offset
        required_hits = 2 if len(anchors) >= 2 else 1
        if best_offset is not None and best_hits >= required_hits:
            page_offset = best_offset
            for entry in outline.entries:
                if (
                    entry.target_page is None
                    and entry.printed_page
                    and entry.printed_page.isdigit()
                ):
                    candidate = int(entry.printed_page) + page_offset
                    if start_page <= candidate <= len(document):
                        entry.target_page = candidate

    # Bookmarks are useful when page labels and the inferred printed-page
    # offset are absent, but only after both stronger signals have been tried.
    # Prefer the candidate nearest the expected physical page when several
    # bookmarks share a short title.
    for entry in outline.entries:
        if entry.target_page is not None:
            continue
        expected_page = (
            int(entry.printed_page) + page_offset
            if page_offset is not None
            and entry.printed_page
            and entry.printed_page.isdigit()
            else None
        )
        candidates = [
            (_similarity(entry.title, title), page)
            for title, page in bookmarks
            if page > (outline.last_page or 0)
        ]
        if expected_page is not None:
            candidates.sort(
                key=lambda value: (value[0], -abs(value[1] - expected_page)),
                reverse=True,
            )
        else:
            candidates.sort(reverse=True)
        if candidates and candidates[0][0] >= 0.84:
            entry.target_page = candidates[0][1]

    # Resolve targets still missing from the actual body text.  Pages that were
    # already located from bookmarks/page labels are intentionally not reparsed;
    # Docling's matched source bounds provide their final within-page position.
    unresolved = [entry for entry in outline.entries if entry.target_page is None]
    if not unresolved:
        return
    for page_number in range(start_page, len(document) + 1):
        if not unresolved:
            break
        lines = page_cache.setdefault(page_number, _page_lines(document[page_number - 1]))
        for entry in list(unresolved):
            matches = [
                (_similarity(entry.title, line.text), line)
                for line in lines
                if 0 < len(line.text) <= 320
            ]
            if not matches:
                continue
            score, line = max(matches, key=lambda value: value[0])
            threshold = 0.9 if len(_match_key(entry.title).split()) <= 2 else 0.82
            if score >= threshold:
                entry.target_page = page_number
                entry.target_y = line.y0
                unresolved.remove(entry)


def _roman_to_int(value: str) -> int | None:
    token = value.casefold()
    if not token or not re.fullmatch(r"[ivxlcdm]+", token):
        return None
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    previous = 0
    for character in reversed(token):
        current = values[character]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total or None


def _chapter_number(value: str) -> int | None:
    token = value.strip()
    return int(token) if token.isdigit() else _roman_to_int(token)


def _chapter_page_from_lines(
    page: pymupdf.Page,
    page_number: int,
    outline_entries: list[TocEntry],
) -> ChapterPage | None:
    """Recognise a chapter title page without relying on the main TOC label.

    VLRC templates use either ``Chapter N`` followed by a large title or a
    single large ``N. Title`` line.  The local contents panel is a strong
    confirmation when present, while the large-title rule covers later report
    templates whose chapter page flows directly into the first subsection.
    """

    lines = _page_lines(page)
    if not lines:
        return None
    height = float(page.rect.height)
    local_contents = any(_INTERNAL_CONTENTS.fullmatch(line.text) for line in lines)

    marker: TextLine | None = None
    number: int | None = None
    inline_title = ""
    for line in lines:
        match = _CHAPTER_MARKER.fullmatch(line.text)
        if not match:
            continue
        candidate_number = _chapter_number(match.group("number"))
        if (
            candidate_number is not None
            and line.y0 <= height * 0.58
            and (line.size >= 14 or line.prominent)
        ):
            marker = line
            number = candidate_number
            inline_title = _clean_text(match.group("title") or "")
            break

    # A complete numbered title near the top is sufficient even when the
    # template omits the word "Chapter" and a literal CONTENTS heading.
    numbered_line: TextLine | None = None
    if marker is None:
        for line in lines:
            match = _NUMBERED_CHAPTER_TITLE.fullmatch(line.text)
            if not match:
                continue
            title = _clean_text(match.group("title"))
            if (
                line.y0 <= height * 0.42
                and line.size >= 15
                and 1 <= len(title.split()) <= 24
            ):
                marker = numbered_line = line
                number = int(match.group("number"))
                inline_title = title
                break

    # A TOC destination provides a third, independent hint for designs whose
    # chapter number and title were split into separate PDF text objects.
    matched_outline: TocEntry | None = None
    if marker is None:
        nearby = [
            entry
            for entry in outline_entries
            if entry.target_page is not None
            and abs(entry.target_page - page_number) <= 1
            and (
                _CHAPTER_MARKER.match(entry.title)
                or _NUMBERED_CHAPTER_TITLE.match(entry.title)
            )
        ]
        for entry in nearby:
            match = _CHAPTER_MARKER.match(entry.title) or _NUMBERED_CHAPTER_TITLE.match(entry.title)
            if not match:
                continue
            candidate_number = _chapter_number(match.group("number"))
            entry_matches = [
                (_similarity(entry.title, line.text), line)
                for line in lines
                if line.y0 <= height * 0.5 and line.size >= 14
            ]
            if not entry_matches:
                continue
            score, line = max(entry_matches, key=lambda value: value[0])
            if score >= 0.7 and candidate_number is not None:
                marker = line
                number = candidate_number
                inline_title = _clean_text(match.groupdict().get("title") or "")
                matched_outline = entry
                break

    if marker is None or number is None:
        return None

    title = inline_title
    if not title and matched_outline is not None:
        title = _NUMBERING_PREFIX.sub("", matched_outline.title).strip()
    if not title:
        # Join the large lines following ``Chapter N``.  Stop before the local
        # contents list; wrapped chapter titles commonly occupy two lines.
        title_lines = [
            line
            for line in lines
            if marker.y0 - 4 <= line.y0 <= marker.y1 + 115
            and line is not marker
            and not _INTERNAL_CONTENTS.fullmatch(line.text)
            and not _PAGE_ONLY.fullmatch(line.text)
            and line.size >= max(16.0, marker.size * 0.72)
            and len(line.text.split()) <= 18
        ]
        title_lines.sort(key=lambda line: (line.y0, line.x0))
        title = _clean_text(" ".join(line.text for line in title_lines[:3]))
    if not title and numbered_line is not None:
        title = inline_title
    if not title:
        return None

    local_entries: list[TocEntry] = []
    if local_contents:
        parsed, _ = _entries_from_page(page, page_number)
        for entry in parsed:
            if (
                _INTERNAL_CONTENTS.fullmatch(entry.title)
                or _similarity(entry.title, title) >= 0.86
                or _CHAPTER_MARKER.fullmatch(entry.title)
            ):
                continue
            entry.level = 2
            local_entries.append(entry)

    return ChapterPage(
        number=number,
        title=f"Chapter {number}: {title}",
        page=page_number,
        top=marker.y0,
        local_entries=tuple(local_entries),
    )


def _detect_chapter_pages(
    document: pymupdf.Document,
    outline: TocOutline,
) -> list[ChapterPage]:
    """Find body chapter pages as a validation layer for TOC H1/H2 labels."""

    candidate_pages = {
        int(entry.target_page)
        for entry in outline.entries
        if entry.target_page is not None
        and (
            _CHAPTER_MARKER.match(entry.title)
            or _NUMBERED_CHAPTER_TITLE.match(entry.title)
        )
    }
    existing_numbers: list[int] = []
    for entry in outline.entries:
        match = _NUMBERED_CHAPTER_TITLE.match(entry.title) or _CHAPTER_MARKER.match(entry.title)
        if match and (number := _chapter_number(match.group("number"))) is not None:
            existing_numbers.append(number)
    existing_numbers = sorted(set(existing_numbers))
    needs_full_scan = not existing_numbers or existing_numbers != list(
        range(existing_numbers[0], existing_numbers[-1] + 1)
    )

    # Explicit Chapter + CONTENTS pages can reveal chapters flattened to H2 in
    # the main TOC.  Plain-text filtering keeps the expensive style parse off
    # ordinary body pages.
    for index, page in enumerate(document):
        if not needs_full_scan and index + 1 in candidate_pages:
            continue
        text = page.get_text("text", sort=True)
        has_marker = bool(re.search(r"(?im)^\s*chapter\s+(?:\d{1,3}|[ivxlcdm]+)\b", text))
        has_contents = bool(re.search(r"(?im)^\s*(?:chapter\s+)?contents\s*$", text))
        has_numbered_title = bool(re.search(r"(?im)^\s*\d{1,3}[.)]\s+\S", text))
        if has_marker and (has_contents or needs_full_scan):
            candidate_pages.add(index + 1)
        elif needs_full_scan and has_numbered_title:
            candidate_pages.add(index + 1)

    chapters = [
        chapter
        for page_number in sorted(candidate_pages)
        if 1 <= page_number <= len(document)
        and (
            chapter := _chapter_page_from_lines(
                document[page_number - 1], page_number, outline.entries
            )
        )
        is not None
    ]
    by_number: dict[int, ChapterPage] = {}
    for chapter in chapters:
        previous = by_number.get(chapter.number)
        if previous is None or chapter.page < previous.page:
            by_number[chapter.number] = chapter
    return sorted(by_number.values(), key=lambda chapter: (chapter.page, chapter.number))


def _repair_outline_from_chapter_pages(
    document: pymupdf.Document,
    outline: TocOutline,
) -> None:
    chapters = _detect_chapter_pages(document, outline)
    if not chapters:
        if not any(entry.level == 1 for entry in outline.entries):
            outline.warnings.append(
                "No chapter title pages could be confirmed; the heading hierarchy may be incomplete."
            )
        return

    for chapter in chapters:
        ranked: list[tuple[float, int, TocEntry]] = []
        for index, entry in enumerate(outline.entries):
            page_distance = (
                abs(entry.target_page - chapter.page)
                if entry.target_page is not None
                else 999
            )
            title_score = _similarity(chapter.title, entry.title)
            number_match = bool(
                re.match(
                    rf"^(?:(?:chapter|part)\s+)?{chapter.number}(?:\b|[.)])",
                    entry.title,
                    re.IGNORECASE,
                )
            )
            if page_distance <= 2 or number_match:
                ranked.append(
                    (title_score + (0.35 if number_match else 0) - page_distance * 0.04, index, entry)
                )
        if ranked and max(ranked, key=lambda value: value[0])[0] >= 0.55:
            _, index, entry = max(ranked, key=lambda value: value[0])
            entry.level = 1
            entry.target_page = chapter.page
            entry.target_y = chapter.top
            continue

        new_entry = TocEntry(
            title=chapter.title,
            level=1,
            printed_page=None,
            toc_page=outline.last_page or 1,
            bbox=(0.0, chapter.top, 0.0, chapter.top),
            target_page=chapter.page,
            target_y=chapter.top,
        )
        insert_at = next(
            (
                index
                for index, entry in enumerate(outline.entries)
                if entry.target_page is not None and entry.target_page > chapter.page
            ),
            len(outline.entries),
        )
        outline.entries.insert(insert_at, new_entry)

    # Between the first and last confirmed chapter page, an H1 must itself be
    # a chapter.  This repairs generic rows such as "Recommendations" or
    # "Conclusion" that typography/indentation occasionally promoted in a
    # flattened TOC.  Front matter and back matter remain top-level links.
    first_page = min(chapter.page for chapter in chapters)
    last_page = max(chapter.page for chapter in chapters)
    chapter_pages = {chapter.page for chapter in chapters}
    for entry in outline.entries:
        if (
            entry.level == 1
            and entry.target_page is not None
            and first_page <= entry.target_page <= last_page
            and not any(abs(entry.target_page - page) <= 1 for page in chapter_pages)
            and not _CHAPTER_MARKER.match(entry.title)
            and not _NUMBERED_CHAPTER_TITLE.match(entry.title)
        ):
            entry.level = 2

    # Local chapter contents pages are a fallback source of H2s.  Only add a
    # row absent from the authoritative printed TOC.
    for chapter in chapters:
        parent_index = next(
            (
                index
                for index, entry in enumerate(outline.entries)
                if entry.level == 1
                and entry.target_page is not None
                and abs(entry.target_page - chapter.page) <= 1
            ),
            None,
        )
        if parent_index is None:
            continue
        insert_at = next(
            (
                index
                for index in range(parent_index + 1, len(outline.entries))
                if outline.entries[index].level == 1
            ),
            len(outline.entries),
        )
        for local in chapter.local_entries:
            if any(_similarity(local.title, entry.title) >= 0.9 for entry in outline.entries):
                continue
            local.level = 2
            outline.entries.insert(insert_at, local)
            insert_at += 1

    # Existing printed-TOC rows never leave their authoritative sequence;
    # inferred chapter/H2 rows are inserted only at their body boundary.
    for sequence, entry in enumerate(outline.entries):
        entry.sequence = sequence


def extract_toc_outline(pdf_path: Path, *, scan_pages: int = 40) -> TocOutline:
    outline = TocOutline()
    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:
        outline.warnings.append(f"Could not read the printed table of contents: {exc}")
        return outline

    with document:
        if len(document) == 0:
            outline.warnings.append(
                "The PDF contains no readable pages; its chapter hierarchy could not be validated."
            )
            return outline
        parsed: list[tuple[int, list[TocEntry], list[TextLine]]] = []
        for page_number in range(1, min(len(document), scan_pages) + 1):
            entries, lines = _entries_from_page(document[page_number - 1], page_number)
            parsed.append((page_number, entries, lines))

        start_index: int | None = None
        for index, (_, entries, lines) in enumerate(parsed):
            if _looks_like_contents_page(entries, lines, is_continuation=False):
                start_index = index
                break
        if start_index is None:
            outline.warnings.append(
                "No printed table of contents was detected; checking chapter title pages."
            )
            _repair_outline_from_chapter_pages(document, outline)
            return outline

        empty_gap = 0
        for page_number, entries, lines in parsed[start_index:]:
            continuation = bool(outline.toc_pages)
            if _looks_like_contents_page(entries, lines, is_continuation=continuation):
                empty_gap = 0
                outline.toc_pages.add(page_number)
                outline.entries.extend(entries)
                heading_regions = [
                    line.bbox for line in lines if _CONTENTS_HEADING.fullmatch(line.text)
                ]
                outline.regions[page_number] = [
                    *heading_regions,
                    *(entry.bbox for entry in entries),
                ]
                continue
            empty_gap += 1
            if empty_gap >= 1:
                break

        deduplicated: list[TocEntry] = []
        seen: set[tuple[str, str | None]] = set()
        for entry in outline.entries:
            key = (_match_key(entry.title), entry.printed_page)
            if not key[0] or key in seen:
                continue
            seen.add(key)
            deduplicated.append(entry)
        outline.entries = _normalise_outline_levels(deduplicated)
        _locate_entry_targets(document, outline)
        _repair_outline_from_chapter_pages(document, outline)
        # Local chapter contents can add missing H2 rows. Resolve their body
        # destinations after the chapter-page repair has completed.
        _locate_entry_targets(document, outline)
    return outline


def _item_page(item: dict[str, Any]) -> int:
    provenance = item.get("prov") or []
    return int(provenance[0].get("page_no", 1)) if provenance else 1


def _item_bounds(
    item: dict[str, Any], page_height: float
) -> tuple[float, float, float, float] | None:
    provenance = item.get("prov") or []
    raw = provenance[0].get("bbox") if provenance else None
    if not raw:
        return None
    left = float(raw.get("l", 0))
    right = float(raw.get("r", 0))
    top = float(raw.get("t", 0))
    bottom = float(raw.get("b", 0))
    if str(raw.get("coord_origin", "")).upper().endswith("BOTTOMLEFT") and page_height:
        top, bottom = page_height - top, page_height - bottom
    return min(left, right), min(top, bottom), max(left, right), max(top, bottom)


def _overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area = max(1.0, (first[2] - first[0]) * (first[3] - first[1]))
    return intersection / area


def _local_contents_lines(block: dict[str, Any]) -> list[str]:
    entries = block.get("list_entries") or []
    values = [str(entry.get("text", "")).strip() for entry in entries]
    if block.get("label") == "box_section":
        for child in block.get("box_section_blocks") or []:
            values.extend(_local_contents_lines(child))
    if not values:
        values = str(block.get("text", "")).splitlines()
    return [
        re.sub(r"^[•·*\-–—]+\s*", "", _clean_text(value))
        for value in values
        if _clean_text(value)
    ]


def _looks_like_local_chapter_contents(
    block: dict[str, Any],
    child_titles: list[str],
) -> bool:
    """Recognise a chapter's compact contents panel without a heading.

    Some VLRC templates put the H1 title and a page-numbered H2 list inside a
    decorative rectangle but omit a literal ``CONTENTS`` label. Matching at
    least two rows back to that chapter's authoritative H2 outline prevents
    the panel from being repeated while leaving ordinary body lists alone.
    """

    if block.get("label") not in {"list", "document_index", "box_section"}:
        return False
    lines = _local_contents_lines(block)
    if len(lines) < 2 or len(child_titles) < 2:
        return False
    matched = sum(
        1
        for line in lines
        if max((_similarity(line, title) for title in child_titles), default=0) >= 0.86
    )
    return matched >= 2 and matched / len(lines) >= 0.45


@dataclass(frozen=True)
class HeadingStyle:
    size: float
    font: str
    flags: int
    left: float
    top: float
    page_width: float
    page_height: float

    @property
    def prominent(self) -> bool:
        font = self.font.casefold()
        return bool(self.flags & 16) or any(
            marker in font for marker in ("bold", "black", "heavy", "semibold")
        )

    @property
    def medium_weight(self) -> bool:
        return "medium" in self.font.casefold()

    @property
    def light_weight(self) -> bool:
        return "light" in self.font.casefold()

    @property
    def top_ratio(self) -> float:
        return self.top / self.page_height if self.page_height else 1.0


def _style_size(value: float) -> float:
    return round(float(value) * 2) / 2


def _heading_style(
    page: pymupdf.Page,
    item: dict[str, Any],
) -> HeadingStyle | None:
    bounds = _item_bounds(item, float(page.rect.height))
    if bounds is None:
        return None
    item_rect = pymupdf.Rect(bounds)
    candidates: list[tuple[float, str, int]] = []
    payload = page.get_text("dict", sort=True)
    for block in payload.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_rect = pymupdf.Rect(span.get("bbox", (0, 0, 0, 0)))
                overlap = (span_rect & item_rect).get_area()
                if overlap < min(span_rect.get_area(), item_rect.get_area()) * 0.16:
                    continue
                candidates.append(
                    (
                        float(span.get("size", 0)),
                        str(span.get("font", "")),
                        int(span.get("flags", 0)),
                    )
                )
    if not candidates:
        return None
    size, font, flags = max(
        candidates,
        key=lambda value: (
            value[0],
            bool(value[2] & 16) or "bold" in value[1].casefold(),
        ),
    )
    return HeadingStyle(
        size=_style_size(size),
        font=font,
        flags=flags,
        left=bounds[0],
        top=bounds[1],
        page_width=float(page.rect.width),
        page_height=float(page.rect.height),
    )


class TocHierarchyResolver:
    """Map Docling items to the printed TOC's two-level navigation outline."""

    def __init__(
        self,
        pdf_path: Path,
        document: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
        main_title_ref: str | None,
    ) -> None:
        self.document = document
        self.all_items = all_items
        self.ordered_references = ordered_references
        self.main_title_ref = main_title_ref
        self.outline = extract_toc_outline(pdf_path)
        self.labels_by_ref: dict[str, str] = {}
        self.text_by_ref: dict[str, str] = {}
        self._match_entries()
        self._classify_body_headings(pdf_path)

    @property
    def warnings(self) -> list[str]:
        return list(self.outline.warnings)

    def _raw_label(self, item: dict[str, Any]) -> str:
        return str(item.get("label", "unspecified")).lower()

    def _page_height(self, page: int) -> float:
        metadata = (self.document.get("pages") or {}).get(
            str(page), (self.document.get("pages") or {}).get(page, {})
        )
        return float(((metadata or {}).get("size") or {}).get("height", 0))

    def is_toc_item(self, item: dict[str, Any]) -> bool:
        page = _item_page(item)
        if page not in self.outline.toc_pages:
            return False
        text = _clean_text(str(item.get("text", "")))
        if _CONTENTS_HEADING.fullmatch(text):
            return True
        raw_label = self._raw_label(item)
        if raw_label == "document_index":
            return True
        bounds = _item_bounds(item, self._page_height(page))
        if bounds is not None:
            return any(
                _overlap_ratio(bounds, region) >= 0.22
                or (
                    region[0] - 4 <= (bounds[0] + bounds[2]) / 2 <= region[2] + 4
                    and region[1] - 4 <= (bounds[1] + bounds[3]) / 2 <= region[3] + 4
                )
                for region in self.outline.regions.get(page, [])
            )
        similarities = [_similarity(text, entry.title) for entry in self.outline.entries]
        return bool(similarities and max(similarities) >= 0.9)

    def _match_entries(self) -> None:
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        for order, reference in enumerate(self.ordered_references):
            item = self.all_items.get(reference)
            if not item or reference == self.main_title_ref or self.is_toc_item(item):
                continue
            raw = self._raw_label(item)
            text = _clean_text(str(item.get("text", "")))
            if (
                raw not in {"title", "section_header", "text", "list_item"}
                or not text
                or len(text) > 320
                or len(text.split()) > 32
            ):
                continue
            candidates.append((order, reference, item))

        used: set[str] = set()
        for entry in self.outline.entries:
            ranked: list[tuple[float, int, str]] = []
            for order, reference, item in candidates:
                if reference in used:
                    continue
                page = _item_page(item)
                if entry.target_page is not None and abs(page - entry.target_page) > 2:
                    continue
                score = _similarity(entry.title, str(item.get("text", "")))
                if self._raw_label(item) in {"text", "list_item"} and (
                    _match_key(
                        str(item.get("text", "")), strip_numbering=True
                    )
                    != _match_key(entry.title, strip_numbering=True)
                ):
                    # Body prose and chapter-content list items are far more
                    # likely than real headings to share a few TOC keywords.
                    # Only an exact normalised title may use those fallback
                    # labels as a destination.
                    continue
                if entry.target_page is not None:
                    score += max(0.0, 0.12 - abs(page - entry.target_page) * 0.05)
                if self._raw_label(item) in {"title", "section_header"}:
                    # Prefer the real body heading over an identically named
                    # row in a chapter's compact contents list. The list row
                    # is often on the nominal printed destination page while
                    # the actual heading starts on the following PDF page.
                    score += 0.16
                ranked.append((score, -order, reference))
            threshold = 0.8 if entry.target_page is not None else 0.88
            reference: str | None = None
            if ranked:
                score, _, best_reference = max(ranked)
                if score >= threshold:
                    reference = best_reference

            if reference is None:
                # Older PDFs sometimes expose inconsistent logical page
                # labels, so a correct printed number can resolve to the wrong
                # physical page.  A unique exact body title is safer than that
                # broken page hint and prevents a genuine TOC H1/H2 from being
                # demoted into the typography-only H3-H5 pass.
                entry_key = _match_key(entry.title, strip_numbering=True)
                exact = [
                    candidate_reference
                    for _, candidate_reference, item in candidates
                    if candidate_reference not in used
                    and entry_key
                    and _match_key(
                        str(item.get("text", "")), strip_numbering=True
                    )
                    == entry_key
                ]
                structural_exact = [
                    candidate_reference
                    for candidate_reference in exact
                    if self._raw_label(self.all_items[candidate_reference])
                    in {"title", "section_header"}
                ]
                if len(structural_exact) == 1:
                    reference = structural_exact[0]
                elif len(exact) == 1:
                    reference = exact[0]

            if reference is None:
                continue
            entry.matched_ref = reference
            used.add(reference)
            self.labels_by_ref[reference] = f"section_header_{entry.level}"
            self.text_by_ref[reference] = entry.title

    def _classify_body_headings(self, pdf_path: Path) -> None:
        """Resolve body headings into contextual H3-H5 levels.

        The printed TOC exclusively owns H1/H2.  Lower levels are ranked
        inside their containing H1 rather than across the entire publication:
        the strongest unmatched style is H3, the next is H4, and the next is
        H5.  Numbering depth can refine that result.  This prevents a report
        that uses several chapter templates from collapsing most headings to
        H5 simply because a different chapter uses larger type.
        """
        candidates: list[tuple[int, str, dict[str, Any], str]] = []
        for order, reference in enumerate(self.ordered_references):
            item = self.all_items.get(reference)
            raw_label = self._raw_label(item or {})
            text = _clean_text(str((item or {}).get("text", "")))
            numbered_text_candidate = bool(
                raw_label == "text"
                and _NUMBERED_BODY_HEADING.match(text)
                and len(text) <= 180
                and len(text.split()) <= 16
                and not text.endswith((".", ";", ":", "?", "!"))
            )
            if (
                not item
                or reference in self.labels_by_ref
                or self.is_toc_item(item)
                or (
                    raw_label != "section_header"
                    and not numbered_text_candidate
                )
            ):
                continue
            if text:
                candidates.append((order, reference, item, text))
        if not candidates or not pdf_path.is_file():
            return

        styles: dict[str, HeadingStyle] = {}
        try:
            with pymupdf.open(pdf_path) as document:
                for _, reference, item, _ in candidates:
                    page_number = _item_page(item)
                    if 1 <= page_number <= len(document):
                        style = _heading_style(document[page_number - 1], item)
                        if style is not None:
                            styles[reference] = style
        except Exception:
            return
        if not styles:
            return

        # Repeated text at a stable top-of-page position on a dense sequence of
        # pages is running furniture, not a subsection.  Requiring at least
        # three nearby occurrences avoids deleting genuine headings such as
        # "Conclusion" that happen to recur in separate chapters.
        repetitions: dict[str, list[tuple[str, int, HeadingStyle]]] = defaultdict(list)
        for _, reference, item, text in candidates:
            style = styles.get(reference)
            if style is not None:
                repetitions[_match_key(text)].append(
                    (reference, _item_page(item), style)
                )
        running_refs: set[str] = set()
        for values in repetitions.values():
            top_values = [value for value in values if value[2].top_ratio <= 0.18]
            pages = sorted({value[1] for value in top_values})
            top_ratios = [value[2].top_ratio for value in top_values]
            if (
                len(pages) >= 3
                and pages[-1] - pages[0] <= len(pages) * 3
                and max(top_ratios, default=0) - min(top_ratios, default=0) <= 0.025
            ):
                running_refs.update(value[0] for value in top_values)

        for _, reference, _, text in candidates:
            style = styles.get(reference)
            if style is None:
                continue
            if _INTERNAL_CONTENTS.fullmatch(text):
                self.labels_by_ref[reference] = "header"
                continue
            if reference in running_refs:
                self.labels_by_ref[reference] = "header"

        h1_positions = sorted(
            (
                int(entry.target_page),
                float(entry.target_y if entry.target_y is not None else -1.0),
                int(entry.sequence),
            )
            for entry in self.outline.entries
            if entry.level == 1 and entry.target_page is not None
        )

        def scope_for(item: dict[str, Any], style: HeadingStyle) -> int:
            if not h1_positions:
                return 0
            position = (_item_page(item), style.top)
            preceding = [
                sequence
                for page, top, sequence in h1_positions
                if (page, top) <= position
            ]
            return preceding[-1] if preceding else -1

        def weight_rank(style: HeadingStyle) -> int:
            if style.prominent:
                return 2
            if style.medium_weight:
                return 1
            return 0

        scoped: dict[int, list[tuple[str, HeadingStyle, str]]] = defaultdict(list)
        for _, reference, item, text in candidates:
            style = styles.get(reference)
            if style is None or reference in self.labels_by_ref:
                continue
            scope = scope_for(item, style)
            if scope < 0:
                # Catalogue/title-page fragments before the first printed TOC
                # destination are not part of the reader hierarchy.
                self.labels_by_ref[reference] = "text"
                continue
            if _NON_BODY_HEADING.match(text):
                self.labels_by_ref[reference] = "text"
                continue
            if _GENERIC_PANEL_HEADING.fullmatch(text):
                # Preserve this as a heading long enough for the visual panel
                # grouper to turn it into a semantic box section.
                self.labels_by_ref[reference] = "section_header_3"
                continue
            if (
                style.light_weight
                or style.size > 18
                or style.size < 9.5
                or len(text) > 220
                or len(text.split()) > 24
            ):
                self.labels_by_ref[reference] = "text"
                continue
            scoped[scope].append((reference, style, text))

        tiers_by_scope: dict[int, list[tuple[float, int]]] = {}
        for scope, values in scoped.items():
            tiers_by_scope[scope] = sorted(
                {(style.size, weight_rank(style)) for _, style, _ in values},
                reverse=True,
            )[:3]

        def numbered_level(text: str) -> int | None:
            match = _NUMBERED_BODY_HEADING.match(text)
            if not match:
                return None
            depth = match.group("number").count(".")
            return min(5, 2 + depth)

        for _, reference, item, text in candidates:
            if reference in self.labels_by_ref:
                continue
            style = styles.get(reference)
            if style is None:
                continue
            scope = scope_for(item, style)
            tiers = tiers_by_scope.get(scope, [])
            key = (style.size, weight_rank(style))
            if key not in tiers:
                self.labels_by_ref[reference] = "text"
                continue
            style_level = min(5, 3 + tiers.index(key))
            explicit_level = numbered_level(text)
            level = max(style_level, explicit_level or 3)
            self.labels_by_ref[reference] = f"section_header_{min(5, level)}"

    def label_for(self, item: dict[str, Any]) -> str:
        reference = str(item.get("self_ref", ""))
        if reference == self.main_title_ref:
            return "title"
        if reference in self.labels_by_ref:
            return self.labels_by_ref[reference]
        raw = self._raw_label(item)
        if raw == "section_header":
            level = item.get("level")
            if not isinstance(level, int):
                level = 1
            return f"section_header_{min(5, max(3, level + 2))}"
        if raw == "title":
            return "text"
        return {
            "box_section": "box_section",
            "caption": "caption",
            "callout": "box_section",
            "checkbox_selected": "form",
            "checkbox_unselected": "form",
            "document_index": "document_index",
            "footnote": "footnote",
            "formula": "formula",
            "list": "list",
            "list_item": "list",
            "page_footer": "footer",
            "page_header": "header",
            "picture": "picture",
            "table": "table",
            "text": "text",
            "unspecified": "unspecified",
        }.get(raw, "unspecified")

    def output_text(self, item: dict[str, Any]) -> str:
        reference = str(item.get("self_ref", ""))
        return self.text_by_ref.get(reference, _clean_text(str(item.get("text", ""))))

    def apply_outline(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        matched_ids = {entry.matched_ref for entry in self.outline.entries if entry.matched_ref}
        output = [block for block in blocks if str(block.get("id", "")) not in matched_ids]
        matched_blocks = {
            str(block.get("id", "")): block for block in blocks if str(block.get("id", ""))
        }

        positioned: list[tuple[float, float, int, dict[str, Any]]] = []
        for index, block in enumerate(output):
            page = int(block.get("page", 1))
            bounds = block.get("source_bounds") or {}
            top = float(bounds.get("top", 10_000 + index))
            positioned.append((float(page), top, 1, block))

        for entry in self.outline.entries:
            if entry.matched_ref and entry.matched_ref in matched_blocks:
                source = matched_blocks[entry.matched_ref]
                page = int(source.get("page", entry.target_page or 1))
                bounds = source.get("source_bounds") or {}
                top = float(bounds.get("top", entry.target_y or -1))
                confidence = source.get("confidence")
                block_id = str(source.get("id", entry.matched_ref))
                source_bounds = source.get("source_bounds")
            else:
                page = int(entry.target_page or max(1, (self.outline.last_page or 0) + 1))
                top = float(entry.target_y if entry.target_y is not None else -1 + entry.sequence / 1000)
                confidence = 1.0
                block_id = f"#/toc-outline/{entry.sequence}"
                source_bounds = None
            positioned.append(
                (
                    float(page),
                    top,
                    0,
                    {
                        "id": block_id,
                        "label": f"section_header_{entry.level}",
                        "text": entry.title,
                        "page": page,
                        "confidence": confidence,
                        "source_bounds": source_bounds,
                        "toc_derived": True,
                        "toc_sequence": entry.sequence,
                    },
                )
            )

        positioned.sort(key=lambda value: (value[0], value[1], value[2]))
        final: list[dict[str, Any]] = []
        seen_headings: set[tuple[str, int]] = set()
        for _, _, _, block in positioned:
            if str(block.get("label", "")).startswith("section_header_"):
                key = (_match_key(str(block.get("text", ""))), int(block.get("page", 1)))
                if key[0] and key in seen_headings:
                    continue
                seen_headings.add(key)
            final.append(block)

        chapter_children_by_page: dict[int, list[str]] = defaultdict(list)
        active_chapter_page: int | None = None
        for entry in self.outline.entries:
            if entry.level == 1:
                active_chapter_page = (
                    int(entry.target_page)
                    if entry.target_page is not None
                    and (
                        _CHAPTER_MARKER.match(entry.title)
                        or _NUMBERED_CHAPTER_TITLE.match(entry.title)
                    )
                    else None
                )
            elif entry.level == 2 and active_chapter_page is not None:
                chapter_children_by_page[active_chapter_page].append(entry.title)

        final = [
            block
            for block in final
            if not _looks_like_local_chapter_contents(
                block,
                chapter_children_by_page.get(int(block.get("page", 1)), []),
            )
        ]

        # Chapter title pages often repeat a compact contents list.  It is not
        # the publication's authoritative TOC and should not be duplicated in
        # the reader body.  Remove the CONTENTS heading and its immediately
        # following list/index on the same page; retain all other page content.
        remove_indices: set[int] = set()
        for index, block in enumerate(final):
            if not _INTERNAL_CONTENTS.fullmatch(
                _clean_text(str(block.get("text", "")))
            ):
                continue
            page = int(block.get("page", 1))
            remove_indices.add(index)
            following = index + 1
            while following < len(final) and int(final[following].get("page", 1)) == page:
                label = str(final[following].get("label", ""))
                if label in {"header", "footer"}:
                    following += 1
                    continue
                if label in {"list", "document_index"}:
                    remove_indices.add(following)
                break
        final = [block for index, block in enumerate(final) if index not in remove_indices]
        for index, block in enumerate(final):
            block["order"] = index
        return final
