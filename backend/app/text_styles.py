"""Recover italic/bold styling that Docling drops for PDF text.

Docling's DoclingDocument schema has a formatting field, but its PDF backend
never populates it, so a footnote like "Principles of Criminal Law" loses its
italic case/title name before it ever reaches review. The PDF itself still
carries the font data, so this module reads it back with pymupdf for a
block's source region and aligns it to the text Docling already extracted.

Docling's text stays authoritative: this only ever produces *ranges* over
that text, never replacement text. Fails closed -- if the PDF region's
characters can't be matched exactly against the block's own text (ignoring
whitespace), no styles are returned at all, so a mis-aligned span can never
italicise the wrong words.

Ranges are offsets into `styles_text`, the exact string they were computed
against. Consumers must apply them only while the block's text still equals
`styles_text` (see `styles_for_text`); any later edit or split of the text
silently reverts to plain rendering."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

_ITALIC_FONT_HINTS = ("italic", "oblique")
_BOLD_FONT_HINTS = ("bold", "black", "heavy")
_PYMUPDF_ITALIC = 2
_PYMUPDF_BOLD = 16


def _span_style(span: dict[str, Any]) -> tuple[bool, bool]:
    font = str(span.get("font", "")).lower()
    flags = int(span.get("flags", 0))
    italic = bool(flags & _PYMUPDF_ITALIC) or any(h in font for h in _ITALIC_FONT_HINTS)
    bold = bool(flags & _PYMUPDF_BOLD) or any(h in font for h in _BOLD_FONT_HINTS)
    return italic, bold


_PUNCTUATION_FOLD = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
        "\u2014": "-", "\u2212": "-",
    }
)
_LEADING_MARKER_RE = re.compile(r"^\d{1,4}")


def _fold(char: str) -> str:
    """Comparison form of one character. Docling and the PDF disagree on
    typographic quotes/dashes and ligatures; folding both sides keeps those
    from defeating an otherwise exact match. May expand to several chars
    (ligatures) or none (soft hyphens)."""
    if char == "\u00ad":
        return ""
    return unicodedata.normalize("NFKC", char.translate(_PUNCTUATION_FOLD))


def _significant(text: str) -> list[tuple[int, str]]:
    """(index in `text`, folded char) for every non-space character; one
    source character may contribute several folded chars."""
    result: list[tuple[int, str]] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        for folded in _fold(char):
            if not folded.isspace():
                result.append((index, folded))
    return result


_MIN_PAGE_SEARCH_CHARS = 25


def _collect_chars(regions: list[dict[str, Any]]) -> list[tuple[str, bool, bool]]:
    chars: list[tuple[str, bool, bool]] = []
    for raw in regions:
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    italic, bold = _span_style(span)
                    for char in str(span.get("text", "")):
                        for folded in _fold(char):
                            if not folded.isspace():
                                chars.append((folded, italic, bold))
    return chars


def extract_style_ranges(page: Any, bounds: dict[str, Any], text: str) -> list[dict[str, Any]] | None:
    """Style runs for `text`, which Docling extracted from `bounds` on
    `page` (a pymupdf page). `bounds` use Docling's top-left origin. Returns
    None when nothing could be aligned confidently, [] when the text is
    confidently aligned but entirely unstyled."""
    try:
        import pymupdf

        clip = pymupdf.Rect(
            float(bounds["left"]),
            float(bounds["top"]),
            float(bounds["right"]),
            float(bounds["bottom"]),
        )
        regions = [page.get_text("dict", clip=clip)]
    except Exception:
        return None

    text_chars = _significant(text)
    if not text_chars:
        return None
    target = "".join(char for _index, char in text_chars)

    # Everything must match exactly, with one allowance: a footnote's leading
    # number often sits just outside the source region the PDF is read from,
    # so when the full text isn't found, retry without that marker (it stays
    # unstyled either way).
    candidates: list[tuple[int, str]] = [(0, target)]
    marker = _LEADING_MARKER_RE.match(text.lstrip())
    if marker:
        skip = sum(
            1
            for index, _c in text_chars
            if index < text.index(marker.group(0)) + len(marker.group(0))
        )
        if skip < len(text_chars):
            candidates.append((skip, "".join(c for _i, c in text_chars[skip:])))

    pdf_chars: list[tuple[str, bool, bool]] = []
    start = -1
    skip = 0
    for scope in ("region", "page"):
        if scope == "page":
            # Docling's bounds sometimes cover only part of the footnote
            # (e.g. just its number), leaving the citation outside the
            # region. Searching the whole page is only trusted when the
            # text occurs exactly once and is long enough not to be a
            # coincidence -- anything else stays plain.
            try:
                regions = [page.get_text("dict")]
            except Exception:
                return None
        pdf_chars = _collect_chars(regions)
        pdf_string = "".join(char for char, _i, _b in pdf_chars)
        for candidate_skip, needle in candidates:
            if scope == "page" and len(needle) < _MIN_PAGE_SEARCH_CHARS:
                continue
            found = pdf_string.find(needle)
            if found < 0:
                continue
            if scope == "page" and pdf_string.find(needle, found + 1) >= 0:
                continue
            start, skip = found, candidate_skip
            break
        if start >= 0:
            break
    if start < 0:
        return None

    # Style per character of `text`; whitespace takes the style of the
    # preceding character only when the following one agrees, so a run of
    # italic words stays one <em> rather than fragmenting at every space.
    per_char: list[tuple[bool, bool]] = [(False, False)] * len(text)
    for offset, (index, _char) in enumerate(text_chars[skip:]):
        _c, italic, bold = pdf_chars[start + offset]
        if italic or bold:
            per_char[index] = (italic, bold)
    previous: tuple[bool, bool] | None = None
    gap: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            gap.append(index)
            continue
        current = per_char[index]
        if previous is not None and previous == current:
            for gap_index in gap:
                per_char[gap_index] = current
        gap = []
        previous = current

    ranges: list[dict[str, Any]] = []
    run_start = 0
    for index in range(1, len(text) + 1):
        if index == len(text) or per_char[index] != per_char[run_start]:
            italic, bold = per_char[run_start]
            if italic or bold:
                ranges.append(
                    {"start": run_start, "end": index, "italic": italic, "bold": bold}
                )
            run_start = index
    return ranges


def styles_for_text(block: dict[str, Any], text: str) -> list[dict[str, Any]]:
    """The block's style ranges, but only while `text` is still exactly the
    string they were computed against."""
    styles = block.get("styles")
    if styles and block.get("styles_text") == text:
        return styles
    return []


def render_styled(text: str, styles: list[dict[str, Any]], offset: int = 0) -> str:
    """HTML-escape `text[offset:]`, wrapping styled runs in <em>/<strong>.
    `styles` ranges index into the full string, so `offset` is how much was
    trimmed from its front (e.g. a footnote's leading number)."""
    visible = text[offset:]
    if not styles:
        return html.escape(visible)
    parts: list[str] = []
    cursor = 0
    for run in sorted(styles, key=lambda r: r["start"]):
        start = max(int(run["start"]) - offset, 0)
        end = min(int(run["end"]) - offset, len(visible))
        if end <= start or start < cursor:
            continue
        parts.append(html.escape(visible[cursor:start]))
        inner = html.escape(visible[start:end])
        if run.get("italic"):
            inner = f"<em>{inner}</em>"
        if run.get("bold"):
            inner = f"<strong>{inner}</strong>"
        parts.append(inner)
        cursor = end
    parts.append(html.escape(visible[cursor:]))
    return "".join(parts)
