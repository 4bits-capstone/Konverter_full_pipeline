from __future__ import annotations

import html
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .metadata_rules import empty_metadata_payload, extract_metadata_from_docling
from .toc_hierarchy import TocHierarchyResolver
from .visual_structure import (
    annotate_pdf_artifacts,
    detect_callout_regions,
    group_visual_callouts,
)
from docling.datamodel.settings import settings

settings.inference.compile_torch_models = False

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
        self._docling_converter: Any = None
        self._docling_lock = threading.Lock()

    def process(self, pdf_path: Path, stage: StageCallback) -> PipelineOutput:
        started = time.monotonic()
        stage(1, "Preparing document")
        raw_document, blocks, doc_confidence, warnings = self._run_docling(
            pdf_path, stage
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
        review_items = self._build_review_items(blocks)
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
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[str]]:
        stage(2, "Extracting content")
        converter = self._get_docling_converter()
        with self._docling_lock:
            result = converter.convert(pdf_path)

        stage(3, "Detecting document structure")
        raw_document = result.document.export_to_dict()
        warnings = annotate_pdf_artifacts(raw_document, pdf_path)
        callout_regions, callout_warnings = detect_callout_regions(pdf_path)
        warnings.extend(callout_warnings)
        cluster_confidences = self._cluster_confidences(result)
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

        confidence = getattr(result, "confidence", None)
        doc_confidence = {
            "layout_score": getattr(confidence, "layout_score", None),
            "mean_score": getattr(confidence, "mean_score", None),
            "mean_grade": str(getattr(confidence, "mean_grade", "")) or None,
            "ocr_score": getattr(confidence, "ocr_score", None),
            "table_score": getattr(confidence, "table_score", None),
            "parse_score": getattr(confidence, "parse_score", None),
        }
        return raw_document, blocks, doc_confidence, warnings

    def _get_docling_converter(self) -> Any:
        if self._docling_converter is not None:
            return self._docling_converter
        with self._docling_lock:
            if self._docling_converter is not None:
                return self._docling_converter
            try:
                from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
                from docling.datamodel.accelerator_options import (
                    AcceleratorDevice,
                    AcceleratorOptions,
                )
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import (
                    HeadingHierarchyOptions,
                    PdfPipelineOptions,
                    TableStructureOptions,
                )
                from docling.document_converter import (
                    DocumentConverter,
                    PdfFormatOption,
                )
            except ImportError as exc:
                raise RuntimeError(
                    'Docling dependencies are missing or outdated. Install with: pip install -e "./backend[docling]"'
                ) from exc

            options = PdfPipelineOptions()
            options.do_ocr = self.settings.do_ocr
            options.do_table_structure = self.settings.do_table_structure
            options.table_structure_options = TableStructureOptions(
                do_cell_matching=True
            )
            options.generate_parsed_pages = True
            options.heading_hierarchy_options = HeadingHierarchyOptions(
                enabled=True,
                use_bookmarks=True,
                use_numbering=True,
                use_style=True,
                max_level=5,
                bookmark_match_threshold=0.76,
            )
            named_devices = {
                name: getattr(AcceleratorDevice, name.upper(), name)
                for name in ("auto", "cpu", "cuda", "mps", "xpu")
            }
            options.accelerator_options = AcceleratorOptions(
                device=named_devices.get(
                    self.settings.docling_device,
                    self.settings.docling_device,
                ),
            )
            self._docling_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=options,
                        backend=PyPdfiumDocumentBackend,
                    )
                }
            )
            return self._docling_converter

    @staticmethod
    def _cluster_confidences(result: Any) -> list[tuple[int, dict[str, float], float]]:
        clusters: list[tuple[int, dict[str, float], float]] = []
        for page in result.pages:
            layout = getattr(getattr(page, "predictions", None), "layout", None)
            for cluster in getattr(layout, "clusters", []) if layout else []:
                bbox = cluster.bbox
                clusters.append(
                    (
                        int(page.page_no),
                        {
                            "l": float(bbox.l),
                            "t": float(bbox.t),
                            "r": float(bbox.r),
                            "b": float(bbox.b),
                        },
                        float(cluster.confidence),
                    )
                )
        return clusters

    @classmethod
    def _confidence_by_reference(
        cls,
        document: dict[str, Any],
        clusters: list[tuple[int, dict[str, float], float]],
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

    @staticmethod
    def _ordered_document_references(
        document: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
    ) -> list[str]:
        text_ranks = {
            str(item.get("self_ref", "")): index
            for index, item in enumerate(document.get("texts", []))
            if str(item.get("self_ref", ""))
        }
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

    def _build_review_items(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for block in blocks:
            label = str(block.get("label", "unspecified"))
            if label in {"header", "footer"}:
                continue
            raw_confidence = block.get("confidence")
            confidence = float(raw_confidence) if raw_confidence is not None else 0.5
            if confidence >= self.settings.high_confidence_threshold:
                continue
            band = (
                "med"
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
                    # low-stakes reference text, so they start pre-accepted
                    # rather than sitting in the queue as "pending" —
                    # reviewers can still reopen and edit any of them.
                    "status": "accepted" if label == "footnote" else "pending",
                    "extracted_text": None if kind == "table" else text,
                    "corrected_text": None,
                    "note": (
                        "Confirm the structure label and extracted content against the original PDF. "
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
