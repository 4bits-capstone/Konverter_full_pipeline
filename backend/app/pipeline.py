from __future__ import annotations

import html
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from . import docling_runner, runpod_client, storage_bucket
from .config import Settings
from .metadata_rules import empty_metadata_payload, extract_metadata_from_docling
from .toc_hierarchy import TocHierarchyResolver
from .visual_structure import (
    _block_in_region,
    annotate_pdf_artifacts,
    detect_callout_regions,
    group_visual_callouts,
    detect_quote_regions,
    group_quote_blocks,
)

StageCallback = Callable[[int, str], None]


LABEL_DISPLAY = {
    "box_section": "Box Section",
    "caption": "Caption",
    "document_index": "Document index",
    "footnote": "Footnote",
    "footer": "Footer",
    "form": "Form",
    "formula": "Formula",
    "header": "Header",
    "list": "List",
    "picture": "Picture",
    "quote": "Quote",
    "section_header_1": "H1",
    "section_header_2": "H2",
    "section_header_3": "H3",
    "section_header_4": "H4",
    "section_header_5": "H5",
    "table": "Table",
    "title": "Title",
    "text": "Text",
}


def _raw_label(item: dict[str, Any]) -> str:
    return str(item.get("label", "unspecified")).lower()


def _first_page(item: dict[str, Any]) -> int:
    provenance = item.get("prov") or []
    return int(provenance[0].get("page_no", 1)) if provenance else 1


_BARE_PAGE_NUMBER_RE = re.compile(
    r"^(?:\d{1,5}|[ivxlcdm]{1,6})(?:\s+(?:\d{1,5}|[ivxlcdm]{1,6}))*$", re.IGNORECASE
)
# A running "which appendix am I in" margin indicator (e.g. a bare "B" next
# to "Appendix B: Consultations") — the same running-marginalia role as a
# bare page number, just a single letter instead of a digit. Deliberately
# narrower than a roman numeral: "A" and "B" aren't valid roman numerals,
# so this can't be folded into _BARE_PAGE_NUMBER_RE above without also
# accepting single letters as page *numbers*, which they never are.
_BARE_MARGIN_LETTER_RE = re.compile(r"^[a-z]$", re.IGNORECASE)
_PAGE_EDGE_MARGIN_POINTS = 45.0
_PAGE_MARGIN_TOP_RATIO = 0.08


def _reclassify_page_edge_numbers_mislabelled_as_text(
    document: dict[str, Any], texts: list[dict[str, Any]]
) -> None:
    """Docling's own layout model occasionally fails to tag a genuine
    running page number (or, the same role, a single-letter "which
    appendix am I in" margin indicator) as "page_header"/"page_footer" at
    all, leaving it raw-labelled plain "text" instead — verified directly
    against a real VLRC report, where every *other* page's number was
    correctly tagged "page_footer" and excluded, but a handful were not,
    surfacing as a lone, floating "8" sitting between two body paragraphs
    with no sentence around it. The same report also had a lone "B"
    sitting immediately before its own "Appendix B: Consultations"
    heading — confirmed against the raw PDF coordinates: the *identical*
    bounding box repeats on every page of that appendix, a textbook
    running margin indicator Docling itself correctly tags "page_header"
    on some pages and plain "text" on others for the exact same printed
    glyph, purely inconsistently.

    The margin-position band alone can't distinguish either shape from a
    split-off footnote marker (both sit in the same bottom-margin region,
    since a footnote apparatus fills that whole area) — but a genuine
    page number or margin letter sits close to the page's own edge (this
    document's own confirmed, correctly-labelled examples print at the
    left edge or within the corner margin on the right), while every
    footnote marker in this corpus is indented to the footnote block's
    own margin (~79pt or more). Requiring that edge-adjacent position, not
    just the margin band alone, is what keeps this from ever mistaking a
    genuine, still-repairable footnote marker for either shape."""
    for item in texts:
        if _raw_label(item) != "text":
            continue
        text = str(item.get("text", ""))
        normalised = _normalise_furniture_text(text)
        if not (
            _BARE_PAGE_NUMBER_RE.match(normalised)
            or _BARE_MARGIN_LETTER_RE.match(normalised)
        ):
            continue
        provenance = item.get("prov") or []
        if not provenance:
            continue
        bbox = provenance[0].get("bbox") or {}
        top, left, right = bbox.get("t"), bbox.get("l"), bbox.get("r")
        page_no = provenance[0].get("page_no")
        if top is None or left is None or page_no is None:
            continue
        pages = document.get("pages") or {}
        page_meta = pages.get(str(page_no), pages.get(page_no, {})) or {}
        size = page_meta.get("size") or {}
        height, width = float(size.get("height", 0)), float(size.get("width", 0))
        if not height:
            continue
        ratio = top / height
        if not (ratio < _PAGE_MARGIN_TOP_RATIO or ratio > 1 - _PAGE_MARGIN_TOP_RATIO):
            continue
        at_left_edge = left < _PAGE_EDGE_MARGIN_POINTS
        at_right_edge = bool(width) and (width - (right or 0)) < _PAGE_EDGE_MARGIN_POINTS
        if not (at_left_edge or at_right_edge):
            continue
        item["label"] = "page_footer" if ratio < 0.5 else "page_header"


def _relabel_misclassified_page_furniture(document: dict[str, Any]) -> None:
    """Docling's own layout model labels every item sitting in a page's
    top/bottom margin "page_header"/"page_footer" — and every consumer
    downstream (_ordered_list_items, the two-column check, exporter.py's
    build_publication) trusts that label completely, silently dropping the
    item before it ever reaches a human reviewer. A running title or a bare
    page number genuinely belongs there. A footnote citation or a short
    erratum note does too, purely by page position — "Consultation 4
    (Victorian Criminal Bar Association)." or "The original terms of
    reference stated section 46(1) which should read section 49." are real
    content, not decoration, and the margin-position label alone can't
    tell them apart.

    What can: a genuine running header/footer recurs, near-verbatim, on
    many pages of the same document — that's the entire reason it's called
    "running". A margin-positioned item that appears once or twice in the
    whole document, and isn't just a bare page number, structurally cannot
    be running furniture regardless of what Docling's layout model called
    it. Relabelling those to "text" here — before any exclusion filter
    reads the label — lets them flow through the normal extraction
    pipeline instead of vanishing before a reviewer ever sees them."""
    texts = document.get("texts", [])
    _reclassify_page_edge_numbers_mislabelled_as_text(document, texts)
    candidates = [
        item for item in texts if _raw_label(item) in {"page_header", "page_footer"}
    ]
    if not candidates:
        return
    # A running footer that prints "218 Report Title" — the page number
    # itself changing every page — would otherwise look unique on every
    # single occurrence and get wrongly recovered as real content; the
    # leading page number is stripped only for this repetition count, not
    # from the bare-page-number check below, which needs the untouched text.
    counts: Counter[str] = Counter(
        _furniture_repetition_key(item.get("text", "")) for item in candidates
    )
    # Real bug found live in "Contempt of Court": a short citation like
    # "Submission 22 (Law Institute of Victoria)." gets footnoted dozens
    # of times throughout a long chapter, so it also recurs verbatim —
    # exactly the signal this function otherwise trusts completely to mean
    # "running furniture, not content". A handful of those same recurring
    # citations happened to lose their footnote number and get raw-labelled
    # "page_header"/"page_footer" by Docling on a few pages, which then
    # met this function's own repeats-3+ bar and were left alone as if
    # they were the report's running title — silently dropping a real,
    # substantive citation the same text is elsewhere correctly footnoted
    # as. Recurrence alone can't tell a repeating citation apart from a
    # repeating disclaimer; cross-checking against Docling's *own* footnote
    # labelling elsewhere in the same document can: a text this function is
    # about to wave through as furniture that Docling itself already
    # labelled "footnote" somewhere else in the document is a footnote,
    # not furniture, regardless of how many times it repeats.
    footnote_texts = {
        _furniture_repetition_key(item.get("text", ""))
        for item in texts
        if _raw_label(item) == "footnote"
    }
    for item in candidates:
        text = str(item.get("text", ""))
        normalised = _normalise_furniture_text(text)
        if _BARE_PAGE_NUMBER_RE.match(normalised) or _BARE_MARGIN_LETTER_RE.match(
            normalised
        ):
            continue
        key = _furniture_repetition_key(text)
        also_a_known_footnote = (
            key in footnote_texts and _FOOTNOTE_CONTENT_RE.search(text)
        )
        if counts[key] >= 3 and not also_a_known_footnote:
            continue
        # A recovered item that itself reads like a genuine footnote —
        # its own bare leading number (no "." or ")" after it, matching
        # how Docling's real footnote items are shaped) plus dominant
        # citation vocabulary — should land as "footnote", not generic
        # "text": _split_merged_footnotes and _repair_split_footnote_markers
        # further down the pipeline both key off label=="footnote" and can
        # then still repair a merged or split marker inside this recovered
        # item exactly as they would for one Docling labelled correctly
        # from the start.
        if (
            _BARE_NUM_RE.match(text)
            and not _PERIOD_NUM_RE.match(text)
            and _FOOTNOTE_CONTENT_RE.search(text)
        ):
            item["label"] = "footnote"
        else:
            item["label"] = "text"


_SIGNIFICANT_IMAGE_MIN_POINTS = 80.0
_DECORATIVE_IMAGE_REPEAT_THRESHOLD = 3


def _synthesize_missing_pictures(document: dict[str, Any], pdf_path: Path | None) -> None:
    """Docling's own layout model occasionally fails to detect a genuine
    embedded image as a picture at all — not a captioning or ordering bug
    like the ones above, a detection gap: the item never appears anywhere
    in the raw extraction, so nothing downstream has anything to render.
    Verified directly against a real VLRC report: "Figure 2: Excerpt from
    the Hindu Community Council of Victoria's 'My Wish' form" (page 95) has
    a real, unique, correctly-captioned reference in the body text, but
    Docling's `pictures` list has zero entries anywhere near it — the same
    was true of the neighbouring Figure 1 and Figure 3's own images on
    pages 93 and 96. All three are genuine, one-off embedded images the
    PDF itself unambiguously contains (pypdfium2/pymupdf's own low-level
    image inventory finds them immediately); Docling's picture-detection
    model simply missed them.

    A large embedded image is not automatically a missing figure, though —
    a decorative background graphic (a chapter-opener watermark, a corner
    design element) is also large, and repeats, verbatim, across dozens of
    pages the same way a running header does. The same repetition signal
    already used for running text furniture applies here: an image whose
    exact xref appears 3 or more times across the document is decoration,
    not content; a genuinely one-off large image on a page Docling has no
    picture for at all is a real, missing figure. Confirmed corpus-wide:
    this distinction cleanly separates "Review of the Bail Act"'s 56 pages
    of a repeating decorative graphic (correctly left alone) from exactly
    the 3 genuine, unique figures per report where this bug actually
    occurs.

    A synthesized picture only ever supplies what real Docling pictures
    already provide to the rest of the pipeline — a page number and a
    bounding box — so it flows through exactly the same picture-block and
    figure-rendering path (service.py's own PDF-region cropping, keyed
    purely on page + bounds) as one Docling detected correctly itself."""
    if not pdf_path or not pdf_path.is_file():
        return
    try:
        import pymupdf
    except Exception:
        return

    pictures = document.setdefault("pictures", [])
    docling_pages = {
        item["prov"][0].get("page_no")
        for item in pictures
        if item.get("prov")
    }
    existing_indices = [
        int(ref.rsplit("/", 1)[-1])
        for item in pictures
        if (ref := str(item.get("self_ref", ""))).rsplit("/", 1)[-1].isdigit()
    ]
    next_index = max(existing_indices, default=-1) + 1

    try:
        with pymupdf.open(pdf_path) as pdf:
            xref_counts: Counter[int] = Counter()
            candidates: list[tuple[int, int, Any, float]] = []
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                for image in page.get_images(full=True):
                    xref = image[0]
                    for rect in page.get_image_rects(xref):
                        if (
                            rect.width >= _SIGNIFICANT_IMAGE_MIN_POINTS
                            and rect.height >= _SIGNIFICANT_IMAGE_MIN_POINTS
                        ):
                            xref_counts[xref] += 1
                            candidates.append(
                                (page_index + 1, xref, rect, page.rect.height)
                            )

            for page_no, xref, rect, page_height in candidates:
                if page_no in docling_pages:
                    continue
                if xref_counts[xref] >= _DECORATIVE_IMAGE_REPEAT_THRESHOLD:
                    continue
                pictures.append(
                    {
                        "self_ref": f"#/pictures/{next_index}",
                        "label": "picture",
                        "captions": [],
                        "prov": [
                            {
                                "page_no": page_no,
                                "bbox": {
                                    "l": rect.x0,
                                    "r": rect.x1,
                                    "t": page_height - rect.y0,
                                    "b": page_height - rect.y1,
                                    "coord_origin": "BOTTOMLEFT",
                                },
                            }
                        ],
                    }
                )
                next_index += 1
    except Exception:
        return


def _normalise_furniture_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


_LEADING_PAGE_NUMBER_RE = re.compile(r"^(?:\d{1,5}|[ivxlcdm]{1,6})\s+", re.IGNORECASE)


def _furniture_repetition_key(value: Any) -> str:
    normalised = _normalise_furniture_text(value)
    return _LEADING_PAGE_NUMBER_RE.sub("", normalised)


_BARE_NUM_RE = re.compile(r"^\d{1,4}\s")
_PERIOD_NUM_RE = re.compile(r"^\d{1,4}[.)]\s")
_FOOTNOTE_CONTENT_RE = re.compile(
    r"\bibid\b|above n\s*\d+|\bs\.?\s*\d+[a-z]?\(|\bss\.?\s*\d+|\(vic\)|\(nsw\)|\(cth\)|"
    r"\(qld\)|\(sa\)|\(wa\)|\(tas\)|\(nt\)|\bv\s[A-Z]|\[\d{4}\]\s*[A-Z]{2,6}|"
    r"\bsubmission[s]?\s*\d|\bconsultation[s]?\s*\d|\bact\s*\d{4}",
    re.IGNORECASE,
)
_FORM_FIELD_LINE_RE = re.compile(
    r"^(?:yes|no)\s*$|\bname\s*:|\baddress\s*:|\bsignature\b|\bquestion\s*\d|"
    r"\btelephone\s*(?:number)?\s*:|\bdate\s*:|please\s+(?:tick|select|specify)",
    re.IGNORECASE,
)


def _is_genuine_form_content(text: str) -> bool:
    """Docling groups a page region into "form_area"/"key_value_area"
    purely from its visual layout (short lines, checkbox glyphs, hanging
    indents) — the same kind of position/shape-only classification behind
    the page_header/page_footer false positives above, and just as prone
    to sweeping in content that merely *looks* similar: a glossary's
    term-then-definition lines, a Table of Legislation, a Table of Cases,
    or a back-of-book index all print as short, discrete lines too.
    Requiring an explicit form signal — a bare "Yes"/"No" checkbox line, a
    "Name:"/"Address:"/"Question N" field prompt — and *not* more citation
    signal than form signal is what actually distinguishes a real form
    field list from a statute or case list dressed the same way on the
    page."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    form_signal = sum(1 for line in lines if _FORM_FIELD_LINE_RE.search(line))
    citation_signal = sum(1 for line in lines if _FOOTNOTE_CONTENT_RE.search(line))
    return form_signal > 0 and form_signal >= citation_signal


_RECOMMENDATION_DIRECTIVE_RE = re.compile(
    r"\bshould be (?:amended|introduced|repealed|required)\b", re.IGNORECASE
)
_RECOMMENDATION_DIRECTIVE_MAX_OFFSET = 100


def _is_recommendation_directive(text: str) -> bool:
    """A genuine recommendation in this corpus, without exception, opens
    with its own directive near the very start — "The Criminal Procedure
    Act 2009 (Vic) should be amended to...", "Magistrates should be
    required to..." — naming the Act/section/body first, then immediately
    stating what should happen to it. A genuine footnote can use this
    exact same phrasing, but only buried inside a *reported* opinion —
    "142 Also submissions 11, 39. The OPP noted that the right of arrest
    ... should be retained" — never within the first ~100 characters,
    since a citation always opens with the citation itself, not a
    directive sentence. Verified directly: every real recommendation
    found live sits at an offset under 90; the one real footnote this
    could be confused with sits at 273."""
    bare_match = _BARE_NUM_RE.match(text)
    start = bare_match.end() if bare_match else 0
    directive_match = _RECOMMENDATION_DIRECTIVE_RE.search(text)
    if not directive_match:
        return False
    return directive_match.start() - start <= _RECOMMENDATION_DIRECTIVE_MAX_OFFSET


def _is_footnote_list_block(block: dict[str, Any]) -> bool:
    entries = block.get("list_entries") or []
    if len(entries) < 2:
        return False
    texts = [str(entry.get("text", "")) for entry in entries]
    if sum(1 for text in texts if _is_recommendation_directive(text)) / len(texts) > 0.5:
        return False
    if not all(_BARE_NUM_RE.match(text) and not _PERIOD_NUM_RE.match(text) for text in texts):
        return False
    matches = sum(1 for text in texts if _FOOTNOTE_CONTENT_RE.search(text))
    return matches / len(texts) > 0.5


def _relabel_footnote_lists(
    blocks: list[dict[str, Any]],
    callout_regions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Docling sometimes emits a numbered footnote apparatus as a single
    ``list`` block rather than individual ``footnote`` blocks. Bare-numbered
    entries (no ``.``/``)`` after the number) whose text is dominated by
    legal-citation vocabulary (``ibid``, ``s 12(3)``, ``[2019] VSC``, etc.)
    are footnotes misclassified as list items, not genuine numbered
    recommendations or findings.

    Real bug found live: a genuine 3-item recommendations list — "53 The
    Act should state...", "54 The Due Diligence Checklist under... Sale of
    Land Act 1962 (Vic) should be amended...", "55 The Sale of Land Act
    1962 (Vic) should be amended..." — got relabelled "footnote" and
    rendered with role="doc-footnote" purely because 2 of 3 entries cite a
    specific "(Vic)" Act, the same vocabulary a genuine citation uses.
    Recommendations that amend a named Act are extremely common in this
    corpus and cannot be told apart from a citation by vocabulary alone.
    What can: this list's own source position. It printed inside a
    visually-detected, bordered/shaded callout panel — footnotes never do;
    they print as small body-adjacent text at a page's bottom margin, not
    inside a highlighted box. A candidate list already sitting inside one
    of the callout regions detect_callout_regions found on this page is
    left alone regardless of its vocabulary."""
    output: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("label") != "list" or not _is_footnote_list_block(block):
            output.append(block)
            continue
        if callout_regions and any(
            _block_in_region(block, region) for region in callout_regions
        ):
            output.append(block)
            continue
        entries = block["list_entries"]
        base_id = str(block.get("id", ""))
        for index, entry in enumerate(entries):
            output.append(
                {
                    "id": f"{base_id}/footnote-{index}",
                    "label": "footnote",
                    "text": str(entry.get("text", "")).strip(),
                    "page": block.get("page"),
                    "confidence": block.get("confidence"),
                    "source_bounds": block.get("source_bounds"),
                }
            )
    return output


_FOOTNOTE_CONTINUATION_INDENT_POINTS = 20.0


def _merge_indented_footnote_continuations(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """A footnote whose citation list is long enough to wrap onto a second
    printed line has that continuation line indented, the same way a
    hanging-indent paragraph aligns its wrapped lines under the text
    rather than the number — verified directly against a real VLRC
    report: footnote 161 reads in full "161 Submissions 6 (Name
    withheld), 10 (Professor Phillip Hamilton), 21 (Pointon Partners
    Lawyers), 23 (Name withheld); 27 (Name withheld), 38 (L. Barry
    Wollmer); Consultation 14 (Robert Mineo)." on the printed page, but
    the wrapped second line ("38 (L. Barry Wollmer); Consultation 14
    (Robert Mineo).") happens to *start* with a number and got extracted
    by Docling as if it were its own separate footnote, raw-labelled
    "footnote" in its own right, sitting ~40pt further right than every
    genuine footnote's own ~80pt margin on the same page.

    Left alone, this doesn't just misrepresent one footnote — it breaks
    _render_footnotes_list's whole-section number check further down the
    pipeline (see _reorder_inverted_adjacent_footnotes below), since "38"
    reads as a real footnote number appearing wildly out of sequence,
    falling the entire section back to doubled-number display. Requiring
    the indent jump (not just "starts with a number") is what keeps this
    from ever swallowing a genuine short footnote that happens to follow
    a long one — a real footnote never starts 20pt or more to the right
    of its own document's standard margin."""
    working = list(blocks)
    remove_indices: set[int] = set()
    anchor_index: int | None = None
    anchor_left: float | None = None
    for index, block in enumerate(working):
        if block.get("label") != "footnote":
            continue
        left = _block_left(block)
        if (
            anchor_index is not None
            and left is not None
            and anchor_left is not None
            and left - anchor_left > _FOOTNOTE_CONTINUATION_INDENT_POINTS
            and block.get("page") == working[anchor_index].get("page")
        ):
            anchor = working[anchor_index]
            anchor["text"] = (
                f"{str(anchor.get('text', '')).rstrip()} "
                f"{str(block.get('text', '')).strip()}"
            )
            remove_indices.add(index)
            continue
        anchor_index, anchor_left = index, left
    return [block for index, block in enumerate(working) if index not in remove_indices]


_BARE_FOOTNOTE_MARKER_RE = re.compile(r"^\d{1,3}$")
_LEADING_FOOTNOTE_NUMBER_RE = re.compile(r"^(\d{1,3})\b")
_EMBEDDED_FOOTNOTE_NUMBER_RE = re.compile(r"\.\s+(\d{1,3})\s+(?=[A-Z])")
# A split-off footnote number and its own citation text sit within a point
# or two of each other on the printed page (the number is a superscript
# glyph immediately beside its own paragraph) -- verified directly against
# a real VLRC report: matching pairs land 0.3-0.4pt apart, while an
# unrelated neighbour is 7+pt away. Comfortably separates the two without
# being so wide it could bridge two genuinely different footnotes.
_FOOTNOTE_MARKER_PROXIMITY_POINTS = 3.0


def _block_top(block: dict[str, Any]) -> float | None:
    bounds = block.get("source_bounds")
    top = bounds.get("top") if isinstance(bounds, dict) else None
    return float(top) if isinstance(top, (int, float)) else None


def _split_merged_footnotes(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Docling sometimes runs two or more consecutive footnotes together
    into a single block, with no boundary between them at all — verified
    directly against a real VLRC report: one "footnote"-labelled block
    reads "6 Smith v Tamworth City Council (1997) 41 NSWLR 680, 693;
    Keller v Keller (2007) 15 VR 667 [6]. 7 Laing v Laing [2014] QSC 194
    [20]", footnote 7's own number and citation buried mid-sentence inside
    footnote 6's block. Since footnote 7 was never its own block, it never
    got its own entry in the footnotes list, and the reader-facing marker
    for it rendered as plain unlinked text instead of a proper footnote
    reference.

    Detection requires the embedded number to be exactly one more than the
    block's own leading number (and the next one after that, and so on for
    a longer chain) — the same discipline as _repair_split_footnote_markers
    — so a coincidental "<number> <Capital letter>" inside a citation's own
    text (a page pinpoint followed by an abbreviation, say) essentially
    never qualifies unless it is actually the report's own next footnote
    number in sequence."""
    output: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("label") != "footnote":
            output.append(block)
            continue
        text = str(block.get("text", ""))
        own_match = _LEADING_FOOTNOTE_NUMBER_RE.match(text.strip())
        if not own_match:
            output.append(block)
            continue
        expected = int(own_match.group(1)) + 1
        split_positions: list[int] = []
        for match in _EMBEDDED_FOOTNOTE_NUMBER_RE.finditer(text):
            if int(match.group(1)) != expected:
                continue
            split_positions.append(match.start(1))
            expected += 1
        if not split_positions:
            output.append(block)
            continue
        base_id = str(block.get("id", ""))
        boundaries = [0, *split_positions, len(text)]
        segment_index = 0
        for start, end in zip(boundaries, boundaries[1:]):
            segment = text[start:end].strip()
            if not segment:
                continue
            new_block = dict(block)
            new_block["text"] = segment
            if segment_index > 0:
                new_block["id"] = f"{base_id}/split-{segment_index}"
            output.append(new_block)
            segment_index += 1
    return output


def _repair_split_footnote_markers(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Docling sometimes splits a footnote's own number off into its own,
    separate block from the citation text that follows it — verified
    directly against real VLRC reports: "2" (label "text") immediately
    followed by "Leeburn v Derndorfer (2004) 14 VR 100, 104" (also label
    "text"), sitting between footnotes 1 and 3, with neither block ever
    reaching the footnotes list — both rendered as ordinary visible body
    paragraphs instead. Sometimes several consecutive numbers split off as
    a run (e.g. "156", "157", "158", "159", "160") before the citation text
    resumes, also as a run of the same length, in the same order — 156
    pairs with the first content block, 157 with the second, and so on.

    Detection is deliberately strict: a candidate marker's number must
    continue the sequence directly from the last real footnote number seen
    (so an unrelated bare number elsewhere in the document, e.g. a stray
    statistic, never matches).

    A marker run and its content run don't always come out to the same
    length, though — verified directly against a real VLRC report: footnote
    16's citation ("Consultations 10 (RSL, Aged and Health Support)...")
    and footnote 17's ("Information given to the Commission by a community
    member on 29 April 2014.") are two separate, consecutively numbered
    footnotes on the printed page, but Docling ran them together into a
    *single* text item with no boundary between them at all — and unlike
    the already-handled case in _split_merged_footnotes above, no number
    is embedded in the merged text to mark where 16 ends and 17 begins, so
    that function's own detection never fires here. That left the marker
    run ["16", "17"] facing only one real content block on its own. Naively
    zipping markers to content front-to-front only produces the right
    answer when it's the *last* marker in the run left without its own
    content; if the gap is anywhere earlier, the same zip would confidently
    glue an unrelated footnote's real text onto the wrong number. What
    actually resolves each pairing correctly: a marker and the content it
    genuinely belongs to sit within a point or two of each other on the
    printed page (the number is a superscript glyph immediately beside its
    own paragraph, split into a separate text run purely by Docling's
    layout model, not by any real distance on the page) — a two-pointer
    walk that only consumes a content block when it is that close to the
    marker being matched skips a marker cleanly, in place, whenever nothing
    in the content stream is positioned as if it were really its own. The
    marker left behind (17 here) still has real content — it's sitting
    merged inside its neighbour's block, unsplittable without a boundary
    signal that was never printed — so it's left as an honest, unrepaired
    bare-number block rather than guessed at; a reviewer checking the
    original PDF can split the merged text by hand if exact per-number
    fidelity matters for that citation."""
    working = list(blocks)
    remove_indices: set[int] = set()
    last_footnote_num: int | None = None
    index = 0
    total = len(working)
    while index < total:
        block = working[index]
        label = block.get("label")
        text = str(block.get("text", "")).strip()

        if label == "footnote":
            match = _LEADING_FOOTNOTE_NUMBER_RE.match(text)
            if match:
                last_footnote_num = int(match.group(1))
            index += 1
            continue

        if (
            label != "text"
            or last_footnote_num is None
            or not _BARE_FOOTNOTE_MARKER_RE.match(text)
            or int(text) != last_footnote_num + 1
        ):
            index += 1
            continue

        marker_indices = [index]
        expected = last_footnote_num + 2
        cursor = index + 1
        while cursor < total:
            candidate = working[cursor]
            candidate_text = str(candidate.get("text", "")).strip()
            if (
                candidate.get("label") in {"text", "footnote"}
                and _BARE_FOOTNOTE_MARKER_RE.match(candidate_text)
                and int(candidate_text) == expected
            ):
                marker_indices.append(cursor)
                expected += 1
                cursor += 1
            else:
                break

        marker_count = len(marker_indices)
        content_indices: list[int] = []
        content_cursor = cursor
        while content_cursor < total and len(content_indices) < marker_count:
            candidate = working[content_cursor]
            candidate_label = candidate.get("label")
            candidate_text = str(candidate.get("text", "")).strip()
            # A "footnote"-labelled block that already has its own leading
            # number is a complete, correctly-numbered footnote — never a
            # split-off marker's missing content. Without this check, the
            # very next normal footnote after the repair zone (or any
            # complete footnote that happens to land in the content
            # window) could get silently swallowed and re-numbered.
            already_complete = candidate_label == "footnote" and bool(
                _LEADING_FOOTNOTE_NUMBER_RE.match(candidate_text)
            )
            if (
                candidate_label in {"text", "footnote"}
                and candidate_text
                and not _BARE_FOOTNOTE_MARKER_RE.match(candidate_text)
                and not already_complete
            ):
                content_indices.append(content_cursor)
                content_cursor += 1
            else:
                break

        if len(content_indices) == marker_count:
            pairs = list(zip(marker_indices, content_indices))
        else:
            pairs = []
            content_pointer = 0
            for candidate_marker_index in marker_indices:
                marker_top = _block_top(working[candidate_marker_index])
                marker_page = working[candidate_marker_index].get("page")
                if content_pointer < len(content_indices):
                    candidate_content_index = content_indices[content_pointer]
                    content_top = _block_top(working[candidate_content_index])
                    content_page = working[candidate_content_index].get("page")
                    if (
                        marker_top is not None
                        and content_top is not None
                        and content_page == marker_page
                        and abs(content_top - marker_top)
                        <= _FOOTNOTE_MARKER_PROXIMITY_POINTS
                    ):
                        pairs.append((candidate_marker_index, candidate_content_index))
                        content_pointer += 1

        for marker_index, content_index in pairs:
            number = int(str(working[marker_index].get("text", "")).strip())
            content_block = working[content_index]
            content_block["label"] = "footnote"
            content_block["text"] = (
                f"{number} {str(content_block.get('text', '')).strip()}"
            )
            remove_indices.add(marker_index)
        # The run's numbers are real, printed footnote numbers regardless of
        # how many of them found their own content -- an unpaired marker
        # still consumes its slot in the sequence, so the next real footnote
        # after it is still checked against the correct expected number.
        last_footnote_num = expected - 1
        index = content_cursor

    return [block for i, block in enumerate(working) if i not in remove_indices]


# A citation continuation line wrapping onto its own row (e.g. "(1989) 4
# BMLR 140; Smith v Tamworth..." continuing the previous footnote) prints
# indented well past the footnote block's own margin — verified directly
# against a real VLRC report, where every genuine footnote starts flush at
# ~79-80pt, while a wrapped continuation that happens to open with what
# looks like a bare number lands 40-60pt further right. Only trusting a
# same-margin pair as a genuine transposition keeps this from ever
# "fixing" one of those continuations into a fabricated, wrong reordering.
_FOOTNOTE_MARGIN_MATCH_POINTS = 5.0


def _reorder_inverted_adjacent_footnotes(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Docling's own reading-order model occasionally emits two adjacent,
    same-page footnotes swapped — verified directly against a real VLRC
    report: footnote 197 ("Consultation 10 (Baw Baw Shire Council).")
    printed physically *below* footnote 196 ("Consultation 9 (Nillumbik
    Shire Council).") on the page, both starting flush at the same ~80pt
    margin, yet extracted in reverse order (197 before 196). Their content
    is completely correct — each has its own real, matching citation — the
    documents' printed numbering itself is what's out of order in the
    extraction, not a labelling problem at all.

    The consequence reaches well past this one pair, though:
    preview_html.py's _render_footnotes_list only trusts a whole section's
    embedded footnote numbers to control the printed <li> numbering when
    *every* consecutive pair increases — a single inverted pair anywhere
    in a 200-footnote section falls the entire section back to plain,
    position-counted numbering, so every footnote's own leading number
    then displays *alongside* the browser's own list count, reading as a
    doubled number throughout the whole section, not just at the one
    inverted pair.

    Distinguishing a genuine transposition from an unrelated shape that
    happens to look similar — a footnote's own citation continuing onto
    a line that starts with what reads like a bare number (a law-report
    volume number, "(1989) 4 BMLR 140...") — is what makes this safe: a
    continuation line's indent sits 40pt or more right of the footnote
    block's own margin, while a genuine transposed footnote starts flush
    at the same margin as its neighbour. Requiring both blocks to be
    complete (matching _LEADING_FOOTNOTE_NUMBER_RE, so neither is a bare,
    still-unrepaired marker) and on the same page keeps this narrowly
    scoped to the one real shape it exists for."""
    working = list(blocks)
    footnote_indices = [i for i, b in enumerate(working) if b.get("label") == "footnote"]
    for position in range(len(footnote_indices) - 1):
        index, next_index = footnote_indices[position], footnote_indices[position + 1]
        first, second = working[index], working[next_index]
        if first.get("page") != second.get("page"):
            continue
        first_match = _LEADING_FOOTNOTE_NUMBER_RE.match(str(first.get("text", "")))
        second_match = _LEADING_FOOTNOTE_NUMBER_RE.match(str(second.get("text", "")))
        if not first_match or not second_match:
            continue
        if int(first_match.group(1)) != int(second_match.group(1)) + 1:
            continue
        first_left = _block_left(first)
        second_left = _block_left(second)
        if (
            first_left is None
            or second_left is None
            or abs(first_left - second_left) > _FOOTNOTE_MARGIN_MATCH_POINTS
        ):
            continue
        # Swap only the two footnotes themselves, not whatever furniture
        # (a page header/footer) may sit between them in the block list --
        # their own relative order is what's inverted, nothing else here.
        working[index], working[next_index] = second, first
    return working


def _block_left(block: dict[str, Any]) -> float | None:
    bounds = block.get("source_bounds")
    left = bounds.get("left") if isinstance(bounds, dict) else None
    return float(left) if isinstance(left, (int, float)) else None


def _plain_text_from_table(table: dict[str, Any] | None) -> str:
    if not table:
        return ""
    rows: list[str] = []
    headers = [str(value).strip() for value in table.get("headers", [])]
    if any(headers):
        rows.append(" | ".join(headers))
    rows.extend(
        " | ".join(str(value).strip() for value in row)
        for row in table.get("rows", [])
    )
    return "\n".join(value for value in rows if value.strip(" |"))


def _normalize_for_text_comparison(value: str) -> str:
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"')
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", "", value)
    return value


_RECOMMENDATION_LANGUAGE_RE = re.compile(
    r"\b(should be amended|should require|should state|should provide|"
    r"should include|should be introduced|should establish|should be enacted|"
    r"the (?:act|commission|government|new act) should)\b",
    re.IGNORECASE,
)
# Genuine footnotes occasionally use "should" too (quoting a court's
# reasoning, or reporting what a submission argued) — requiring the absence
# of ordinary citation vocabulary is what separates a real citation ("Victoria
# Legal Aid thought ... should ...", still describing a source) from the
# report's own recommendation text, which cites nothing.
_FOOTNOTE_CITATION_MARKERS_RE = re.compile(
    r"\b(submissions?|consultations?|roundtables?|\(vic\)|\(cth\)|\(nsw\)|ibid|"
    r"see also|see, eg|report no|discussion paper|vlrc|https?://|www\.)\b",
    re.IGNORECASE,
)
# "The Commission [is asked to] examine whether X should be introduced" is
# describing a question under consideration (often paraphrasing the terms
# of reference), not asserting the report's own recommendation the way
# "X should be introduced" alone would — verified directly against a real
# footnote this flagged incorrectly. Requiring "whether" to appear shortly
# before the matched phrase, not just anywhere in a long paragraph, keeps
# this scoped to that specific construction rather than excluding any
# recommendation that happens to mention "whether" somewhere else in it.
_EXPLORATORY_FRAMING_RE = re.compile(
    r"\bwhether\b(?:\W+\w+){0,15}?\W+should\b", re.IGNORECASE
)


def _looks_like_misclassified_recommendation(text: str) -> bool:
    """A block labelled "footnote" whose own wording reads like the
    report's own recommendation ("The Act should state...", "...should be
    amended by...") rather than a citation. Verified directly against a
    real 364-page VLRC report: three of its own numbered recommendations
    had been labelled "footnote" instead of "list" — confidence 0.92, so
    they never even reached the review queue at all, silently shipping
    core recommendation content buried in the footnotes section instead
    of the body. Docling's own confidence score doesn't catch this
    (a wrong label can still be a "confident" one); nothing about
    citation-text accuracy would catch it either, since the extracted
    text itself was character-for-character correct — only the label was
    wrong."""
    if _EXPLORATORY_FRAMING_RE.search(text):
        return False
    return bool(_RECOMMENDATION_LANGUAGE_RE.search(text)) and not (
        _FOOTNOTE_CITATION_MARKERS_RE.search(text)
    )


def _footnote_text_is_trustworthy(
    page_textpage: Any, bounds: dict[str, Any], docling_text: str
) -> bool:
    """Independently re-extract this footnote's own region of the PDF —
    bypassing Docling's own text entirely — and compare. Verified directly
    against a real 364-page VLRC report: Docling occasionally truncates a
    footnote to its last sentence, or interleaves two adjacent footnotes'
    content across their block boundaries, while reporting an unremarkable
    confidence score for the (wrong) result — auto-accepting every
    footnote regardless would ship those silently. `page_textpage` covers
    the whole page in PDF canvas units (bottom-left origin); `bounds`
    (from Docling's own provenance) is top-down, hence the flip below.
    A merely dropped hyphen at a line-wrap (common in wrapped citation
    URLs) is treated as untrustworthy too, same as real content loss —
    both mean the extracted text doesn't match the source, just at
    different severities, and either way a person should confirm it."""
    page_height = float(bounds.get("page_height", 0))
    if page_height <= 0:
        return False
    try:
        independent_text = page_textpage.get_text_bounded(
            left=float(bounds.get("left", 0)),
            right=float(bounds.get("right", 0)),
            bottom=page_height - float(bounds.get("bottom", 0)),
            top=page_height - float(bounds.get("top", 0)),
        )
    except Exception:
        return False
    doc_norm = _normalize_for_text_comparison(docling_text)
    ind_norm = _normalize_for_text_comparison(independent_text)
    if not doc_norm or not ind_norm:
        return False
    # The independent crop commonly bleeds in stray characters from the
    # line directly above (ascenders/descenders clipped at the bbox edge)
    # without losing any of the footnote's own text — a true superset —
    # so a substring match either way, not exact equality, is the right
    # bar for "matches", verified against the real document above.
    return doc_norm in ind_norm or ind_norm in doc_norm


def _effective_font_size(page: Any, bounds: dict[str, Any]) -> float | None:
    """Best-effort rendered font size (in points) for whatever text sits
    inside this block's own bounding region, read directly from the PDF's
    text objects — Docling's own output carries no font-size info at all
    for PDF-extracted text (the same underlying gap as the italics
    finding: pdfium exposes real font metrics per text object, but
    Docling's PDF backend never propagates them into TextItem). Majority
    vote across every text object whose bounds overlap the region, rather
    than the first one found — verified directly against a real document
    that a tight crop can occasionally overlap a sliver of an adjacent,
    differently-sized text run, and picking the first match alone turned
    one in eighty genuine footnotes into a false outlier."""
    page_height = float(bounds.get("page_height", 0))
    if page_height <= 0:
        return None
    left = float(bounds.get("left", 0))
    right = float(bounds.get("right", 0))
    top_pdf = page_height - float(bounds.get("top", 0))
    bottom_pdf = page_height - float(bounds.get("bottom", 0))
    sizes: list[float] = []
    try:
        for obj in page.get_objects():
            if obj.type != 1:  # 1 = text object
                continue
            object_left, object_bottom, object_right, object_top = obj.get_bounds()
            if (
                object_right < left
                or object_left > right
                or object_top < bottom_pdf
                or object_bottom > top_pdf
            ):
                continue
            try:
                font_size = obj.get_font_size()
                a, b, _c, _d, _e, _f = obj.get_matrix().get()
                scale = (a * a + b * b) ** 0.5
                sizes.append(round(font_size * scale, 1))
            except Exception:
                continue
    except Exception:
        return None
    if not sizes:
        return None
    return Counter(sizes).most_common(1)[0][0]


def _typical_body_text_font_size(
    blocks: list[dict[str, Any]],
    footnote_page: Callable[[int], Any],
    footnote_baseline: float | None,
) -> float | None:
    """This document's own typical body-paragraph font size, for judging
    whether an oversized footnote is genuinely body-sized rather than just
    a second, still-small footnote convention elsewhere in the document
    (a real, confirmed case: one report used 6.5pt for most footnotes and
    8.6pt for an entire other chapter's — still clearly footnote-scaled,
    not a misclassification). "text"-labelled blocks are the natural
    source for this, but verified directly against two real reports:
    "text" as a whole skews toward the *footnote* size, not the body
    size — captions, run-overs, and other small print also end up
    labelled "text" — so raw-moding all of it picks the wrong baseline.
    Excluding anything close to the already-known footnote baseline
    before taking the mode is what actually recovers the true body size
    (confirmed: 10.5pt in both reports checked, exactly matching where
    the real bug's mislabelled recommendations rendered)."""
    sizes: list[float] = []
    for block in blocks:
        if block.get("label") != "text":
            continue
        bounds = block.get("source_bounds")
        if not bounds:
            continue
        page = footnote_page(int(block.get("page", 1)))
        if page is None:
            continue
        size = _effective_font_size(page, bounds)
        if size is None:
            continue
        if footnote_baseline is not None and abs(size - footnote_baseline) <= 1.0:
            continue
        sizes.append(size)
    if not sizes:
        return None
    return Counter(sizes).most_common(1)[0][0]


def _footnote_font_size_outlier(
    block_font_size: float | None,
    baseline_footnote_font_size: float | None,
    body_text_font_size: float | None,
) -> bool:
    """Whether a footnote-labelled block's own font size looks like this
    document's *body* text rather than its own footnotes — verified
    directly against real documents: genuine footnotes hold one
    consistent size document-wide (6.5pt across 80/80 samples in one
    report, 7.0pt across 80/80 in another), while three of a report's own
    numbered recommendations mislabelled as footnotes rendered at the
    same size as that document's body text, 10.5pt — a 62% jump from its
    6.5pt footnote baseline. Being meaningfully bigger than the footnote
    baseline alone isn't enough to call it a misclassification, though —
    a real report was found using two legitimate footnote sizes for
    different chapters (6.5pt and 8.6pt, both clearly footnote-scaled),
    which a baseline-only check would wrongly flag 86 times over. Only
    when the size is *also* close to the document's own body-text size is
    it actually the body-sized content the check exists to catch."""
    if block_font_size is None or baseline_footnote_font_size is None or (
        baseline_footnote_font_size <= 0
    ):
        return False
    meaningfully_larger_than_footnotes = (
        block_font_size >= baseline_footnote_font_size * 1.2
        and block_font_size - baseline_footnote_font_size >= 1.0
    )
    if not meaningfully_larger_than_footnotes:
        return False
    if body_text_font_size is None:
        # No reliable body-text baseline to confirm against — fall back
        # to the baseline-only signal rather than staying silent.
        return True
    return abs(block_font_size - body_text_font_size) <= 1.0


@dataclass
class PipelineOutput:
    blocks: list[dict[str, Any]]
    review_items: list[dict[str, Any]]
    metadata_payload: dict[str, Any]
    raw_docling: dict[str, Any]
    doc_confidence: dict[str, Any]
    warnings: list[str]
    elapsed_seconds: float


class KonverterPipeline:
    def __init__(self, settings: Settings):
        self.settings = settings

    def process(
        self, pdf_path: Path, stage: StageCallback, document_id: str
    ) -> PipelineOutput:
        started = time.monotonic()
        stage(1, "Preparing document")
        raw_document, blocks, doc_confidence, warnings = self._run_docling(
            pdf_path, stage, document_id
        )

        stage(4, "Extracting metadata")
        try:
            metadata_payload = extract_metadata_from_docling(
                raw_document,
                pdf_path,
                self.settings,
            )
        except Exception as exc:
            warnings.append(f"Rule-based metadata extraction failed: {exc}")
            metadata_payload = empty_metadata_payload(self.settings)

        stage(5, "Scoring confidence")
        review_items = self._build_review_items(blocks, pdf_path)
        stage(6, "Preparing review")
        return PipelineOutput(
            blocks=blocks,
            review_items=review_items,
            metadata_payload=metadata_payload,
            raw_docling=raw_document,
            doc_confidence=doc_confidence,
            warnings=warnings,
            elapsed_seconds=time.monotonic() - started,
        )

    def _run_docling(
        self,
        pdf_path: Path,
        stage: StageCallback,
        document_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[str]]:
        stage(2, "Extracting content")
        if self.settings.docling_mode == "remote":
            docling_result = self._run_docling_remote(pdf_path, stage, document_id)
        else:
            docling_result = docling_runner.run_docling(
                pdf_path,
                {
                    "do_ocr": self.settings.do_ocr,
                    "do_table_structure": self.settings.do_table_structure,
                    "device": self.settings.docling_device,
                },
            )
        raw_document = docling_result["raw_docling"]
        cluster_confidences = docling_result["cluster_confidences"]
        doc_confidence = docling_result["doc_confidence"]

        stage(3, "Detecting document structure")
        warnings = annotate_pdf_artifacts(raw_document, pdf_path)
        _relabel_misclassified_page_furniture(raw_document)
        _synthesize_missing_pictures(raw_document, pdf_path)
        callout_regions, callout_warnings = detect_callout_regions(pdf_path)
        warnings.extend(callout_warnings)
        quote_regions, quote_warnings = detect_quote_regions(pdf_path)
        warnings.extend(quote_warnings)
        confidence_by_ref = self._confidence_by_reference(
            raw_document, cluster_confidences
        )
        blocks, hierarchy_warnings = self._blocks_from_document(
            raw_document,
            confidence_by_ref,
            pdf_path,
        )
        warnings.extend(hierarchy_warnings)
        blocks = _split_merged_footnotes(blocks)
        blocks = _merge_indented_footnote_continuations(blocks)
        blocks = _repair_split_footnote_markers(blocks)
        blocks = _reorder_inverted_adjacent_footnotes(blocks)
        blocks = _relabel_footnote_lists(blocks, callout_regions)
        blocks = group_visual_callouts(blocks, callout_regions)
        blocks = group_quote_blocks(blocks, quote_regions)

        return raw_document, blocks, doc_confidence, warnings

    def _run_docling_remote(
        self,
        pdf_path: Path,
        stage: StageCallback,
        document_id: str,
    ) -> dict[str, Any]:
        ttl = self.settings.signed_url_ttl
        source_key = storage_bucket.upload_pdf(self.settings, document_id, pdf_path)
        download_url = storage_bucket.signed_download_url(
            self.settings, source_key, ttl
        )
        result_key = f"{document_id}/docling.json"
        upload_target = storage_bucket.signed_upload_target(
            self.settings, result_key, ttl
        )
        job_id = runpod_client.submit(
            self.settings.docling_endpoint_url,
            self.settings.runpod_api_key,
            {
                "pdf_download_url": download_url,
                "result_upload": upload_target,
                "options": {
                    "do_ocr": self.settings.do_ocr,
                    "do_table_structure": self.settings.do_table_structure,
                    "device": "cuda",
                },
            },
        )
        runpod_client.poll(
            self.settings.docling_endpoint_url,
            self.settings.runpod_api_key,
            job_id,
            on_progress=lambda: stage(2, "Waiting for remote GPU worker"),
        )
        return storage_bucket.download_json(self.settings, result_key)

    @classmethod
    def _confidence_by_reference(
        cls,
        document: dict[str, Any],
        clusters: list[list[Any]],
    ) -> dict[str, float | None]:
        pages = document.get("pages", {})
        clusters_by_page: dict[int, list[tuple[dict[str, float], float]]] = {}
        for page_no, bounds, confidence in clusters:
            clusters_by_page.setdefault(page_no, []).append((bounds, confidence))
        output: dict[str, float | None] = {}
        for collection in (
            "texts",
            "pictures",
            "tables",
            "form_items",
            "key_value_items",
        ):
            for item in document.get(collection, []):
                best_iou = 0.0
                best_confidence: float | None = None
                for provenance in item.get("prov", []):
                    page_no = int(provenance.get("page_no", 1))
                    bbox = provenance.get("bbox")
                    page_meta = pages.get(str(page_no), pages.get(page_no, {}))
                    height = float(page_meta.get("size", {}).get("height", 0))
                    if not bbox:
                        continue
                    normalised = cls._top_left_bbox(bbox, height)
                    for cluster_bbox, confidence in clusters_by_page.get(page_no, ()):
                        iou = cls._bbox_iou(normalised, cluster_bbox)
                        if iou > best_iou:
                            best_iou = iou
                            best_confidence = confidence
                output[str(item.get("self_ref", ""))] = (
                    best_confidence if best_iou > 0.3 else None
                )
        return output

    @staticmethod
    def _top_left_bbox(bbox: dict[str, Any], page_height: float) -> dict[str, float]:
        left = float(bbox.get("l", 0))
        right = float(bbox.get("r", 0))
        top = float(bbox.get("t", 0))
        bottom = float(bbox.get("b", 0))
        if (
            str(bbox.get("coord_origin", "")).upper().endswith("BOTTOMLEFT")
            and page_height > 0
        ):
            top, bottom = page_height - top, page_height - bottom
        return {
            "l": min(left, right),
            "t": min(top, bottom),
            "r": max(left, right),
            "b": max(top, bottom),
        }

    @staticmethod
    def _bbox_iou(first: dict[str, float], second: dict[str, float]) -> float:
        left = max(first["l"], second["l"])
        top = max(first["t"], second["t"])
        right = min(first["r"], second["r"])
        bottom = min(first["b"], second["b"])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        first_area = max(0.0, first["r"] - first["l"]) * max(
            0.0, first["b"] - first["t"]
        )
        second_area = max(0.0, second["r"] - second["l"]) * max(
            0.0, second["b"] - second["t"]
        )
        union = first_area + second_area - intersection
        return intersection / union if union else 0.0

    def _blocks_from_document(
        self,
        document: dict[str, Any],
        confidence_by_ref: dict[str, float | None],
        pdf_path: Path | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        all_items: dict[str, dict[str, Any]] = {}
        for collection in (
            "texts",
            "pictures",
            "tables",
            "groups",
            "form_items",
            "key_value_items",
        ):
            for item in document.get(collection, []):
                reference = str(item.get("self_ref", ""))
                if reference:
                    all_items[reference] = item

        ordered_references = self._ordered_document_references(document, all_items)
        source_path = pdf_path or Path("__missing_source__.pdf")
        resolver = TocHierarchyResolver(
            source_path,
            document,
            all_items,
            ordered_references,
            self._main_title_reference(all_items, ordered_references),
        )

        blocks: list[dict[str, Any]] = []
        consumed: set[str] = set()

        def visit(reference: str) -> None:
            item = all_items.get(reference)
            if not item or reference in consumed:
                return
            consumed.add(reference)
            if (item.get("meta") or {}).get("konverter_exclude_from_output"):
                return
            if resolver.is_toc_item(item):
                return

            raw_label = _raw_label(item)
            children = [
                str(child.get("$ref", "")) for child in item.get("children", [])
            ]

            if raw_label == "list" and children:
                child_items = [all_items.get(child) for child in children]
                child_items = self._ordered_list_items(
                    document,
                    [
                        child
                        for child in child_items
                        if child
                        and not resolver.is_toc_item(child)
                        and not (child.get("meta") or {}).get(
                            "konverter_exclude_from_output"
                        )
                    ],
                )
                consumed.update(child for child in children if child)
                if not child_items:
                    return
                list_entries = []
                for child in child_items:
                    value = str(child.get("text", "")).strip()
                    marker = str(child.get("marker", "")).strip()
                    list_entries.append(
                        {
                            "text": value,
                            "marker": marker,
                            "enumerated": bool(child.get("enumerated")),
                            "level": self._list_item_level(child),
                        }
                    )
                confidences = [
                    confidence_by_ref.get(str(child.get("self_ref", "")))
                    for child in child_items
                ]
                valid_confidences = [
                    value for value in confidences if value is not None
                ]
                blocks.append(
                    {
                        "id": reference,
                        "label": "list",
                        "text": "\n".join(
                            (
                                f"{entry['marker']} {entry['text']}".strip()
                                if entry["marker"]
                                else f"• {entry['text']}"
                            )
                            for entry in list_entries
                            if entry["text"]
                        ),
                        "list_items": [
                            entry["text"] for entry in list_entries if entry["text"]
                        ],
                        "list_entries": [
                            entry for entry in list_entries if entry["text"]
                        ],
                        "page": _first_page(child_items[0]),
                        "confidence": (
                            min(valid_confidences) if valid_confidences else None
                        ),
                        "source_bounds": self._combined_source_bounds(
                            document, child_items
                        ),
                    }
                )
                return

            if raw_label in {"form_area", "key_value_area"} and children:
                child_items = [all_items.get(child) for child in children]
                child_items = [
                    child
                    for child in child_items
                    if child and not resolver.is_toc_item(child)
                ]
                consumed.update(child for child in children if child)
                if not child_items:
                    return
                aggregated_text = "\n".join(
                    str(child.get("text", "")).strip() for child in child_items
                )
                blocks.append(
                    {
                        "id": reference,
                        "label": (
                            "form"
                            if _is_genuine_form_content(aggregated_text)
                            else "text"
                        ),
                        "text": aggregated_text,
                        "page": _first_page(child_items[0]),
                        "confidence": None,
                        "source_bounds": self._combined_source_bounds(
                            document, child_items
                        ),
                    }
                )
                return

            if raw_label in {"table", "document_index"}:
                table = self._table_data(item)
                caption = self._item_caption(item, all_items)
                if caption:
                    table["caption"] = caption
                blocks.append(
                    {
                        "id": reference,
                        "label": (
                            "document_index"
                            if raw_label == "document_index"
                            else "table"
                        ),
                        "text": _plain_text_from_table(table),
                        "table_data": table,
                        "page": _first_page(item),
                        "confidence": confidence_by_ref.get(reference),
                        "source_bounds": self._combined_source_bounds(document, [item]),
                    }
                )
                return

            if raw_label == "group":
                return

            label = resolver.label_for(item)
            text = resolver.output_text(item)
            if label == "picture" and not text:
                text = str(item.get("caption", "")).strip()
            blocks.append(
                {
                    "id": reference,
                    "label": label,
                    "text": text,
                    "page": _first_page(item),
                    "confidence": confidence_by_ref.get(reference),
                    "source_bounds": self._combined_source_bounds(document, [item]),
                }
            )

        for reference in ordered_references:
            visit(reference)

        text_ranks = {
            str(item.get("self_ref", "")): index
            for index, item in enumerate(document.get("texts", []))
            if str(item.get("self_ref", ""))
        }
        rank_cache: dict[str, int] = {}

        def source_rank(reference: str, active: set[str] | None = None) -> int:
            if reference in text_ranks:
                return text_ranks[reference]
            if reference in rank_cache:
                return rank_cache[reference]
            active = set() if active is None else active
            if reference in active:
                return len(text_ranks) + len(rank_cache)
            active.add(reference)
            item = all_items.get(reference) or {}
            child_ranks = [
                source_rank(str(child.get("$ref", "")), active)
                for child in item.get("children", [])
                if str(child.get("$ref", ""))
            ]
            active.remove(reference)
            rank = min(child_ranks) if child_ranks else len(text_ranks) + len(rank_cache)
            rank_cache[reference] = rank
            return rank

        visible_blocks = [
            block
            for block in blocks
            if block["label"] not in {"header", "footer"} or block.get("text")
        ]
        original_order = {id(block): index for index, block in enumerate(visible_blocks)}
        visible_blocks.sort(
            key=lambda block: (
                int(block.get("page", 1)),
                source_rank(str(block.get("id", ""))),
                original_order[id(block)],
            )
        )
        ordered_blocks = [
            {**block, "order": index} for index, block in enumerate(visible_blocks)
        ]
        if not any(block["label"] == "title" for block in ordered_blocks):
            source_name = str(document.get("name", "Document")).replace("_", " ").strip()
            ordered_blocks.insert(
                0,
                {
                    "id": "#/synthetic/document-title",
                    "label": "title",
                    "text": source_name or "Document",
                    "page": 1,
                    "confidence": 1.0,
                    "order": 0,
                },
            )
        ordered_blocks = resolver.apply_outline(ordered_blocks)
        for index, block in enumerate(ordered_blocks):
            block["order"] = index
        return ordered_blocks, resolver.warnings

    @staticmethod
    def _list_item_level(item: dict[str, Any]) -> int:
        metadata = item.get("meta") or {}
        for value in (
            item.get("level"),
            item.get("nesting_level"),
            metadata.get("level"),
            metadata.get("nesting_level"),
            metadata.get("indentation_level"),
        ):
            if isinstance(value, int):
                return max(0, value)
        return 0

    @staticmethod
    def _item_caption(
        item: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
    ) -> str:
        direct = str(item.get("caption") or "").strip()
        if direct:
            return direct
        values: list[str] = []
        for candidate in item.get("captions") or []:
            if isinstance(candidate, dict):
                reference = str(candidate.get("$ref", ""))
                value = str((all_items.get(reference) or {}).get("text", "")).strip()
            else:
                value = str(candidate).strip()
            if value:
                values.append(value)
        return " ".join(values)

    @classmethod
    def _ordered_list_items(
        cls,
        document: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        eligible = [
            item
            for item in items
            if not (item.get("meta") or {}).get("konverter_exclude_from_output")
            and _raw_label(item) not in {"page_header", "page_footer"}
        ]
        original_order = {id(item): index for index, item in enumerate(eligible)}
        pages: dict[int, list[tuple[dict[str, Any], dict[str, float] | None]]] = {}
        for item in eligible:
            page = _first_page(item)
            page_meta = document.get("pages", {}).get(
                str(page), document.get("pages", {}).get(page, {})
            )
            page_height = float(page_meta.get("size", {}).get("height", 0))
            provenance = item.get("prov") or []
            raw_box = provenance[0].get("bbox") if provenance else None
            bounds = cls._top_left_bbox(raw_box, page_height) if raw_box else None
            pages.setdefault(page, []).append((item, bounds))

        ordered: list[dict[str, Any]] = []
        for page in sorted(pages):
            page_entries = pages[page]
            bounded = [(item, box) for item, box in page_entries if box is not None]
            unbounded = [item for item, box in page_entries if box is None]
            page_meta = document.get("pages", {}).get(
                str(page), document.get("pages", {}).get(page, {})
            )
            page_width = float(page_meta.get("size", {}).get("width", 0))
            lefts = sorted(float(box["l"]) for _, box in bounded)
            split_threshold = max(48.0, page_width * 0.12)
            column_starts: list[float] = []
            for left in lefts:
                if not column_starts or left - column_starts[-1] > split_threshold:
                    column_starts.append(left)
                else:
                    column_starts[-1] = (column_starts[-1] + left) / 2
            columns: list[list[tuple[dict[str, Any], dict[str, float]]]] = [
                [] for _ in column_starts
            ]
            for item, box in bounded:
                assert box is not None
                column = min(
                    range(len(column_starts)),
                    key=lambda index: abs(float(box["l"]) - column_starts[index]),
                )
                columns[column].append((item, box))
            for column in columns:
                column.sort(
                    key=lambda value: (
                        float(value[1]["t"]),
                        float(value[1]["l"]),
                        original_order[id(value[0])],
                    )
                )
                ordered.extend(item for item, _ in column)
            ordered.extend(sorted(unbounded, key=lambda item: original_order[id(item)]))
        return ordered

    @classmethod
    def _column_aware_text_ranks(cls, document: dict[str, Any]) -> dict[str, float]:
        """Docling's own top-level reading order (the position of each item
        in document["texts"]) already gets used as-is for ordinary
        single-column pages, but on a genuine side-by-side layout — a
        front-matter page pairing "Terms of Reference" with an
        "Acknowledgements" contributor list, or a two-column Bibliography —
        it interleaves the two columns by raw vertical position instead of
        reading one column fully before the other. _ordered_list_items
        (below) already solves exactly this problem for a single list
        group's own children; this applies the same column-clustering
        approach to top-level page content generally.

        Deliberately conservative: a page is only reordered when at least
        two clusters carry more than one item each — a lone off-column
        element (a caption, a pull-quote, a stray page number) must never
        register as a second column on its own. Column *count* rather
        than share, since a genuine column can legitimately be a handful
        of dense, multi-line blocks against dozens of short ones in the
        other column — that imbalance is normal, not a sign the split is
        spurious. Most pages have no genuine second column and pass
        through with their original order completely untouched."""
        texts = document.get("texts", [])
        original_index = {
            str(item.get("self_ref", "")): index
            for index, item in enumerate(texts)
            if str(item.get("self_ref", ""))
        }
        pages: dict[int, list[tuple[int, str, dict[str, float]]]] = {}
        for index, item in enumerate(texts):
            reference = str(item.get("self_ref", ""))
            if not reference or _raw_label(item) in {"page_header", "page_footer"}:
                continue
            provenance = item.get("prov") or []
            raw_box = provenance[0].get("bbox") if provenance else None
            if not raw_box:
                continue
            page = _first_page(item)
            page_meta = document.get("pages", {}).get(
                str(page), document.get("pages", {}).get(page, {})
            )
            page_height = float(page_meta.get("size", {}).get("height", 0))
            page_width = float(page_meta.get("size", {}).get("width", 0))
            if page_width <= 0:
                continue
            bounds = cls._top_left_bbox(raw_box, page_height)
            pages.setdefault(page, []).append((index, reference, bounds))

        ranks = dict(original_index)
        for page, entries in pages.items():
            if len(entries) < 4:
                continue
            page_meta = document.get("pages", {}).get(
                str(page), document.get("pages", {}).get(page, {})
            )
            page_width = float(page_meta.get("size", {}).get("width", 0))
            threshold = max(page_width * 0.35, 150.0)
            lefts = sorted({round(bounds["l"]) for _, _, bounds in entries})
            clusters: list[list[float]] = []
            for left in lefts:
                if not clusters or left - clusters[-1][-1] > threshold:
                    clusters.append([left])
                else:
                    clusters[-1].append(left)
            if len(clusters) < 2:
                continue

            def column_of(left: float) -> int:
                return min(
                    range(len(clusters)),
                    key=lambda cluster_index: min(
                        abs(left - value) for value in clusters[cluster_index]
                    ),
                )

            columned = [
                (index, reference, bounds, column_of(bounds["l"]))
                for index, reference, bounds in entries
            ]
            column_counts = Counter(column for *_, column in columned)
            if any(count < 2 for count in column_counts.values()):
                continue

            columned.sort(
                key=lambda value: (value[3], value[2]["t"], value[2]["l"], value[0])
            )
            base = min(index for index, *_ in entries)
            for offset, (_, reference, _, _) in enumerate(columned):
                ranks[reference] = base + offset * 0.001
        return ranks

    @classmethod
    def _ordered_document_references(
        cls,
        document: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
    ) -> list[str]:
        text_ranks = cls._column_aware_text_ranks(document)
        rank_cache: dict[str, float] = {}

        def earliest_rank(reference: str, active: set[str] | None = None) -> float:
            if reference in text_ranks:
                return float(text_ranks[reference])
            if reference in rank_cache:
                return rank_cache[reference]
            active = set() if active is None else active
            if reference in active:
                return float(len(text_ranks) + len(rank_cache))
            active.add(reference)
            item = all_items.get(reference) or {}
            child_ranks = [
                earliest_rank(str(child.get("$ref", "")), active)
                for child in item.get("children", [])
                if str(child.get("$ref", ""))
            ]
            active.remove(reference)
            rank = (
                min(child_ranks) - 0.25
                if child_ranks
                else len(text_ranks) + _first_page(item)
            )
            rank_cache[reference] = rank
            return rank

        return sorted(
            all_items,
            key=lambda reference: (
                earliest_rank(reference),
                1 if reference in text_ranks else 0,
                reference,
            ),
        )

    @classmethod
    def _combined_source_bounds(
        cls,
        document: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not items:
            return None
        page = _first_page(items[0])
        page_meta = document.get("pages", {}).get(
            str(page), document.get("pages", {}).get(page, {})
        )
        page_size = page_meta.get("size", {})
        page_width = float(page_size.get("width", 0))
        page_height = float(page_size.get("height", 0))
        boxes: list[dict[str, float]] = []
        for item in items:
            for provenance in item.get("prov") or []:
                if int(provenance.get("page_no", page)) != page:
                    continue
                raw_box = provenance.get("bbox")
                if raw_box:
                    boxes.append(cls._top_left_bbox(raw_box, page_height))
        if not boxes or page_width <= 0 or page_height <= 0:
            return None
        return {
            "left": min(box["l"] for box in boxes),
            "top": min(box["t"] for box in boxes),
            "right": max(box["r"] for box in boxes),
            "bottom": max(box["b"] for box in boxes),
            "page_width": page_width,
            "page_height": page_height,
        }

    @staticmethod
    def _main_title_reference(
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> str | None:
        # Real bug found live: this candidate list only screens by page
        # number and a small set of front-matter headings, then hands the
        # win to whichever remaining candidate has the most title-shaped
        # *length* (see the scoring below) — so a National Library
        # Cataloguing-in-Publication notice, a "This report reflects the
        # law..." disclaimer sentence, a phone/fax contact block, a
        # citation-style note ("follows the Melbourne University Law
        # Review Association"), or a credits-page "Name (team leader)"
        # line all outscored the real title outright in 9 of 11 real
        # documents, purely because they happened to be the only (or
        # longest) survivor once the obviously-wrong ones were excluded.
        # Extended past the original front-matter-heading list to
        # disqualify each of those concrete shapes.
        excluded = re.compile(
            r"^(?:contents|preface|terms of reference|glossary|recommendations?|"
            r"report\b|isbn\b|©|a community law reform project|"
            r"this (?:report|publication)\b|published by\b)|"
            r"cataloguing-in-publication|\blaw review association\b|"
            r"\btelephone\b|\bfreecall\b|\bfax\b|"
            r"\((?:team leader|chair|deputy chair|commissioner|author|editor|"
            r"solicitor|barrister)\)",
            re.IGNORECASE,
        )
        address = re.compile(
            r"\b(?:gpo|po)\s+box\b|\b(?:victoria|melbourne)\s+\d{4}\b",
            re.IGNORECASE,
        )
        ranked: list[tuple[float, int, str]] = []
        for order, reference in enumerate(ordered_references):
            item = all_items.get(reference)
            if not item or (item.get("meta") or {}).get("konverter_exclude_from_output"):
                continue
            raw_label = _raw_label(item)
            if raw_label not in {"title", "section_header"}:
                continue
            page = _first_page(item)
            text = str(item.get("text", "")).strip()
            if page > 5 or not text or excluded.search(text) or address.search(text):
                continue
            level = item.get("level")
            score = 1000.0 if raw_label == "title" else 0.0
            if isinstance(level, int) and level == 1:
                score += 80
            word_count = len(text.split())
            if 18 <= len(text) <= 120:
                score += 100
            if 3 <= word_count <= 14:
                score += 100
            if word_count <= 2:
                score -= 100
            score += min(len(text), 80) * 0.5
            ranked.append((score, -order, reference))
        return max(ranked, default=(0.0, 0, ""))[2] or None

    @staticmethod
    def _table_data(item: dict[str, Any]) -> dict[str, Any]:
        data = item.get("data", {})
        row_count = int(data.get("num_rows", 0))
        column_count = int(data.get("num_cols", 0))
        cells = data.get("table_cells") or [
            cell for row in data.get("grid", []) for cell in row
        ]
        if not row_count:
            row_count = (
                max(
                    (int(cell.get("start_row_offset_idx", 0)) for cell in cells),
                    default=-1,
                )
                + 1
            )
        if not column_count:
            column_count = (
                max(
                    (int(cell.get("start_col_offset_idx", 0)) for cell in cells),
                    default=-1,
                )
                + 1
            )
        row_count = max(1, row_count)
        column_count = max(1, column_count)
        matrix = [["" for _ in range(column_count)] for _ in range(row_count)]
        header_row = False
        for cell in cells:
            row = min(row_count - 1, int(cell.get("start_row_offset_idx", 0)))
            column = min(column_count - 1, int(cell.get("start_col_offset_idx", 0)))
            matrix[row][column] = str(cell.get("text", "")).strip()
            header_row = header_row or (row == 0 and bool(cell.get("column_header")))
        if header_row:
            return {"headers": matrix[0], "rows": matrix[1:]}
        return {
            "headers": [f"Column {index + 1}" for index in range(column_count)],
            "rows": matrix,
        }

    def _build_review_items(
        self, blocks: list[dict[str, Any]], pdf_path: Path | None = None
    ) -> list[dict[str, Any]]:
        # No PDF to independently check against (e.g. these blocks came
        # from something other than a real, on-disk PDF) means footnote
        # cross-validation simply isn't possible — that's "unverifiable",
        # not "verified and wrong", so it falls back to the old trust-by-
        # default behaviour rather than marking every footnote pending.
        if pdf_path is None:
            return self._build_review_items_with_textpages(blocks, None)

        try:
            pdf_document = pdfium.PdfDocument(str(pdf_path))
        except Exception:
            return self._build_review_items_with_textpages(blocks, None)

        textpage_cache: dict[int, Any] = {}
        page_cache: dict[int, Any] = {}

        def footnote_textpage(page_number: int) -> Any:
            if page_number not in textpage_cache:
                try:
                    textpage_cache[page_number] = pdf_document[
                        page_number - 1
                    ].get_textpage()
                except Exception:
                    textpage_cache[page_number] = None
            return textpage_cache[page_number]

        def footnote_page(page_number: int) -> Any:
            if page_number not in page_cache:
                try:
                    page_cache[page_number] = pdf_document[page_number - 1]
                except Exception:
                    page_cache[page_number] = None
            return page_cache[page_number]

        try:
            return self._build_review_items_with_textpages(
                blocks, footnote_textpage, footnote_page
            )
        finally:
            pdf_document.close()

    def _build_review_items_with_textpages(
        self,
        blocks: list[dict[str, Any]],
        footnote_textpage: Callable[[int], Any] | None,
        footnote_page: Callable[[int], Any] | None = None,
    ) -> list[dict[str, Any]]:
        # A footnote's font size only means something relative to this
        # document's *own* typical footnote size — different reports use
        # different point sizes for their own footnotes — so the baseline
        # has to be calibrated per document, from whichever footnotes look
        # ordinary, before any individual block can be judged an outlier.
        footnote_font_sizes: dict[str, float] = {}
        baseline_footnote_font_size: float | None = None
        if footnote_page is not None:
            sizes_seen: list[float] = []
            for block in blocks:
                if block.get("label") != "footnote":
                    continue
                bounds = block.get("source_bounds")
                if not bounds:
                    continue
                page_number = int(block.get("page", 1))
                page = footnote_page(page_number)
                if page is None:
                    continue
                size = _effective_font_size(page, bounds)
                if size is not None:
                    footnote_font_sizes[str(block.get("id"))] = size
                    sizes_seen.append(size)
            if sizes_seen:
                baseline_footnote_font_size = Counter(sizes_seen).most_common(1)[0][0]
        body_text_font_size = (
            _typical_body_text_font_size(blocks, footnote_page, baseline_footnote_font_size)
            if footnote_page is not None
            else None
        )

        items: list[dict[str, Any]] = []
        for block in blocks:
            label = str(block.get("label", "unspecified"))
            if label in {"header", "footer"}:
                continue
            raw_confidence = block.get("confidence")
            confidence = float(raw_confidence) if raw_confidence is not None else 0.5
            # A footnote whose own wording reads like the report's own
            # recommendation, not a citation, must reach the review queue
            # regardless of how confident Docling was about the label —
            # a real case of this carried confidence 0.92, comfortably
            # above the threshold that would otherwise skip it entirely.
            suspected_misclassified_recommendation = label == "footnote" and (
                _looks_like_misclassified_recommendation(str(block.get("text", "")))
            )
            # Same idea, but content-agnostic: a footnote rendered at this
            # document's own body-text size rather than its footnote size
            # is suspicious regardless of what it says — this is what
            # actually caught the real recommendation-mislabelling case
            # above, independent of its wording.
            suspected_font_size_outlier = label == "footnote" and (
                _footnote_font_size_outlier(
                    footnote_font_sizes.get(str(block.get("id"))),
                    baseline_footnote_font_size,
                    body_text_font_size,
                )
            )
            suspected_misclassified_footnote = (
                suspected_misclassified_recommendation or suspected_font_size_outlier
            )
            if (
                confidence >= self.settings.high_confidence_threshold
                and not suspected_misclassified_footnote
            ):
                continue
            band = (
                "high"
                if confidence >= self.settings.high_confidence_threshold
                else "med"
                if confidence >= self.settings.medium_confidence_threshold
                else "low"
            )
            table_data = block.get("table_data")
            kind = "table" if label in {"table", "document_index"} else "text"
            display = LABEL_DISPLAY.get(label, label.replace("_", " ").title())
            page = int(block.get("page", 1))
            text = str(block.get("text", ""))
            if not text.strip() and not table_data and not block.get("source_bounds"):
                # Empty synthetic groups have no visual or semantic evidence to
                # review. Keeping them creates indistinguishable full-page flags.
                continue
            source_text = html.escape(text[:1800]).replace("\n", "<br>")
            list_items = block.get("list_items")
            list_entries = block.get("list_entries")
            box_children = block.get("box_section_blocks")
            # The evidence preview above (source_text) should show exactly
            # what was extracted, bullets and all — but the *editable*
            # starting text shouldn't, or a reviewer who only changes the
            # structure label without retyping anything carries stray
            # marker characters (e.g. "• 114 Ibid 98.") straight into a
            # footnote/quote/heading correction instead of clean text.
            # list_items already has markers parsed out; the raw block
            # text doesn't. A box_section absorbs whichever blocks a
            # detected panel contains (group_visual_callouts in
            # visual_structure.py) and its own "text" is just those
            # children's raw text joined verbatim, so a bulleted list
            # trapped inside a callout panel leaks the same marker
            # characters through the box_section path instead — falling
            # back to each child's own list_items (when it has one) fixes
            # that case the same way.
            #
            # One marker shape is not stray decoration though: a VLRC-style
            # decimal paragraph number ("2.39", "7.2") is the report's own
            # numbering system, and the exporter (_list_publication_blocks)
            # specifically detects and preserves it in the final output.
            # Stripping it here — the same way a bullet or "(a)" gets
            # stripped — would show the reviewer text that doesn't match
            # what actually gets published, and would silently drop the
            # number for good the moment they save any text edit (a
            # corrected_text edit is re-parsed from scratch and never sees
            # the original marker to recover it from).
            def _decimal_paragraph_marker(entry: dict[str, Any]) -> str:
                marker = str(entry.get("marker", "")).strip()
                return marker if re.fullmatch(r"\d+(?:\.\d+)+", marker) else ""

            if list_entries and any(
                _decimal_paragraph_marker(entry) for entry in list_entries
            ):
                extracted_lines = []
                for entry in list_entries:
                    entry_text = str(entry.get("text", "")).strip()
                    if not entry_text:
                        continue
                    marker = _decimal_paragraph_marker(entry)
                    extracted_lines.append(
                        f"{marker} {entry_text}" if marker else entry_text
                    )
                extracted_text = "\n".join(extracted_lines)
            elif list_items:
                extracted_text = "\n".join(
                    str(item).strip() for item in list_items if str(item).strip()
                )
            elif box_children:
                extracted_text = "\n\n".join(
                    cleaned
                    for child in box_children
                    if (
                        cleaned := (
                            "\n".join(
                                str(item).strip()
                                for item in child.get("list_items") or []
                                if str(item).strip()
                            )
                            if child.get("list_items")
                            else str(child.get("text", "")).strip()
                        )
                    )
                )
            else:
                extracted_text = text
            # A footnote only gets the pipeline's own pre-acceptance if an
            # independent re-extraction of its own PDF region agrees with
            # Docling's text — verified directly against a real 364-page
            # VLRC report, Docling's confidence score does not catch this:
            # a truncated-to-one-sentence footnote and two footnotes with
            # interleaved content both carried unremarkable confidence.
            # One that fails cross-validation goes to the ordinary
            # "pending" queue instead, same as everything else.
            if label != "footnote":
                footnote_verified = False
            elif suspected_misclassified_footnote:
                # The text itself can be character-for-character correct —
                # this isn't a content problem, it's a label problem, so
                # passing the text cross-check below wouldn't make it any
                # more trustworthy as a *footnote*.
                footnote_verified = False
            elif footnote_textpage is None:
                # No PDF available to check against at all (e.g. these
                # blocks didn't come from a real on-disk PDF) — that's
                # "unverifiable", not "verified and wrong".
                footnote_verified = True
            else:
                footnote_verified = bool(
                    block.get("source_bounds")
                ) and _footnote_text_is_trustworthy(
                    footnote_textpage(page), block.get("source_bounds") or {}, text
                )
            items.append(
                {
                    "id": f"review-{len(items) + 1}",
                    "block_id": block["id"],
                    "type": label,
                    "label": display,
                    "page": page,
                    "confidence": round(confidence, 4),
                    "band": band,
                    "title": f"{display} structure needs confirmation",
                    "kind": kind,
                    # Footnotes are already non-blocking (see
                    # NON_BLOCKING_REVIEW_TYPES in service.py) and are
                    # low-stakes reference text, so a verified one starts
                    # pre-accepted rather than sitting in the queue as
                    # "pending" — reviewers can still reopen and edit any
                    # of them regardless.
                    "status": "accepted" if footnote_verified else "pending",
                    # This "accepted" is the pipeline's own decision, made
                    # before any person has seen the item — distinct from a
                    # reviewer's own accept/edit/bulk-resolve action later
                    # (service.py sets "reviewer" the moment one happens).
                    # Docling itself cannot preserve italics on PDF text
                    # (verified directly: the DoclingDocument schema has a
                    # formatting field, but the PDF backend never populates
                    # it — see BACKEND_AUDIT.md), so an auto-accepted legal
                    # citation with an italicised case name has already
                    # silently lost that styling by the time it reaches
                    # this queue; flagging it as system-validated rather
                    # than indistinguishable from a human decision keeps
                    # that gap visible instead of hidden.
                    "reviewed_by": "system" if footnote_verified else None,
                    "extracted_text": None if kind == "table" else extracted_text,
                    "corrected_text": None,
                    "note": (
                        "This reads like one of the report's own recommendations, not a "
                        "citation — check whether the structure label should be changed "
                        "(e.g. to List)."
                        if suspected_misclassified_recommendation
                        else "This is printed at the same size as body text, not this "
                        "document's usual (smaller) footnote size — check whether it's "
                        "really a footnote or should have a different structure label."
                        if suspected_font_size_outlier
                        else "Confirm the structure label and extracted content against the original PDF. "
                        "Changing the structure also changes the correction editor and generated output."
                    ),
                    "table_data": table_data if kind == "table" else None,
                    "corrected_table": None,
                    "source": {
                        "page": page,
                        "bounds": block.get("source_bounds"),
                        "html": (
                            f'<div class="hl" style="font-size:11px;line-height:1.55">{source_text or "[No text extracted]"}</div>'
                            f'<span class="page-num">Page {page}</span>'
                        ),
                    },
                }
            )
        return items
