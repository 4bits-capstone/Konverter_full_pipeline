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
    "unspecified": "Unspecified",
}


def _raw_label(item: dict[str, Any]) -> str:
    return str(item.get("label", "unspecified")).lower()


def _first_page(item: dict[str, Any]) -> int:
    provenance = item.get("prov") or []
    return int(provenance[0].get("page_no", 1)) if provenance else 1


_BARE_NUM_RE = re.compile(r"^\d{1,4}\s")
_PERIOD_NUM_RE = re.compile(r"^\d{1,4}[.)]\s")
_FOOTNOTE_CONTENT_RE = re.compile(
    r"\bibid\b|above n\s*\d+|\bs\.?\s*\d+[a-z]?\(|\bss\.?\s*\d+|\(vic\)|\(nsw\)|\(cth\)|"
    r"\(qld\)|\(sa\)|\(wa\)|\(tas\)|\(nt\)|\bv\s[A-Z]|\[\d{4}\]\s*[A-Z]{2,6}|"
    r"\bsubmission[s]?\s*\d|\bconsultation[s]?\s*\d|\bact\s*\d{4}",
    re.IGNORECASE,
)


def _is_footnote_list_block(block: dict[str, Any]) -> bool:
    entries = block.get("list_entries") or []
    if len(entries) < 2:
        return False
    texts = [str(entry.get("text", "")) for entry in entries]
    if not all(_BARE_NUM_RE.match(text) and not _PERIOD_NUM_RE.match(text) for text in texts):
        return False
    matches = sum(1 for text in texts if _FOOTNOTE_CONTENT_RE.search(text))
    return matches / len(texts) > 0.5


def _relabel_footnote_lists(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Docling sometimes emits a numbered footnote apparatus as a single
    ``list`` block rather than individual ``footnote`` blocks. Bare-numbered
    entries (no ``.``/``)`` after the number) whose text is dominated by
    legal-citation vocabulary (``ibid``, ``s 12(3)``, ``[2019] VSC``, etc.)
    are footnotes misclassified as list items, not genuine numbered
    recommendations or findings.
    """
    output: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("label") != "list" or not _is_footnote_list_block(block):
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
        blocks = _relabel_footnote_lists(blocks)
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
                blocks.append(
                    {
                        "id": reference,
                        "label": "form",
                        "text": "\n".join(
                            str(child.get("text", "")).strip()
                            for child in child_items
                        ),
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
        excluded = re.compile(
            r"^(?:contents|preface|terms of reference|glossary|recommendations?|"
            r"report\b|isbn\b|©|a community law reform project)",
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
