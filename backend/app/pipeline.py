from __future__ import annotations

import html
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .config import Settings
from .hierarchy_integration import apply_hierarchy, attach_hierarchy_metadata
from .metadata_rules import empty_metadata_payload, extract_metadata_from_docling
from .visual_structure import (
    annotate_pdf_artifacts,
    detect_callout_regions,
    group_visual_callouts,
)

StageCallback = Callable[[int, str], None]


LABEL_DISPLAY = {
    "caption": "Caption",
    "callout": "Callout",
    "chapter_title": "Chapter title",
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

RAW_LABEL_MAP = {
    "caption": "caption",
    "callout": "callout",
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
    "section_header": "section_header_1",
    "table": "table",
    "title": "title",
    "text": "text",
    "unspecified": "unspecified",
}


def _effective_raw_label(item: dict[str, Any]) -> str:
    """Return the postprocessed label, restoring only hierarchy-backed headers."""
    raw = str(item.get("label", "unspecified")).lower()
    metadata = item.get("meta") or {}
    original = str(metadata.get("konverter_original_label", "")).lower()
    if (
        raw == "text"
        and original == "section_header"
        and isinstance(metadata.get("hf__heading_level"), int)
    ):
        return "section_header"
    return raw


def _first_page(item: dict[str, Any]) -> int:
    provenance = item.get("prov") or []
    return int(provenance[0].get("page_no", 1)) if provenance else 1


def _plain_text_from_table(table: dict[str, Any] | None) -> str:
    if not table:
        return ""
    rows = []
    headers = [str(value).strip() for value in table.get("headers", [])]
    if any(headers):
        rows.append(" | ".join(headers))
    rows.extend(
        " | ".join(str(value).strip() for value in row) for row in table.get("rows", [])
    )
    return "\n".join(value for value in rows if value.strip(" |"))


class HeadingResolver:
    """Resolve headings from chapter opening pages before falling back to style."""

    def __init__(
        self,
        main_title_ref: str | None,
        all_items: dict[str, dict[str, Any]] | None = None,
        ordered_references: list[str] | None = None,
    ) -> None:
        self.main_title_ref = main_title_ref
        self.current_chapter_key = ""
        self.current_outline: set[str] = set()
        self.chapter_outlines: dict[str, set[str]] = {}
        self.chapter_title_refs: set[str] = set()
        self.chapter_contents_refs: set[str] = set()
        self.lower_level_by_size: dict[float, int] = {}
        self.h2_font_floor: float | None = None
        self._hierarchy_base_level: int | None = None
        self._pending_split_chapter_page: int | None = None
        # Last emitted heading level, used to prevent skipped levels
        # (e.g. an H4 directly after a chapter title) in the nested output.
        self._last_heading_level = 1
        if all_items is not None and ordered_references is not None:
            self._discover_chapter_outlines(all_items, ordered_references)
            self._build_lower_style_levels(all_items)

    def label_for(self, item: dict[str, Any]) -> str:
        raw = _effective_raw_label(item)
        reference = str(item.get("self_ref", ""))
        text = str(item.get("text", "")).strip()

        if reference == self.main_title_ref:
            self._last_heading_level = 1
            return "title"

        if reference in self.chapter_title_refs or raw == "title":
            self._select_chapter(text, item)
            self._last_heading_level = 1
            return "chapter_title"

        if raw != "section_header":
            return RAW_LABEL_MAP.get(raw, "unspecified")

        if self._pending_split_chapter_page is not None:
            pending_page = self._pending_split_chapter_page
            self._pending_split_chapter_page = None
            if _first_page(item) == pending_page and text:
                self.current_chapter_key = self._chapter_key(text)
                self.current_outline = self.chapter_outlines.get(
                    self.current_chapter_key, set()
                )
                self._last_heading_level = 1
                return "chapter_title_continuation"

        chapter_key = self._chapter_key(text)
        if self.current_chapter_key and chapter_key == self.current_chapter_key:
            self._set_hierarchy_base(item)
            self._last_heading_level = 1
            return "section_header_1"
        if chapter_key in self.current_outline:
            self._last_heading_level = 2
            return "section_header_2"

        if not self.current_chapter_key and (
            self._is_numbered_chapter(text) or self._is_named_back_matter_chapter(text)
        ):
            self._select_chapter(text, item)
            self._last_heading_level = 1
            return "chapter_title"
        if self._is_numbered_chapter(text) and chapter_key != self.current_chapter_key:
            self._select_chapter(text, item)
            self._last_heading_level = 1
            return "chapter_title"
        if (
            self._is_named_back_matter_chapter(text)
            and chapter_key != self.current_chapter_key
        ):
            self._select_chapter(text, item)
            self._last_heading_level = 1
            return "chapter_title"

        inferred = self._infer_lower_level(item)
        level = max(2, min(inferred, self._last_heading_level + 1, 5))
        self._last_heading_level = level
        return f"section_header_{level}"

    def is_chapter_contents(self, reference: str) -> bool:
        return reference in self.chapter_contents_refs

    def _select_chapter(
        self,
        text: str,
        item: dict[str, Any] | None = None,
    ) -> None:
        self.current_chapter_key = self._chapter_key(text)
        self.current_outline = self.chapter_outlines.get(
            self.current_chapter_key, set()
        )
        self._hierarchy_base_level = None
        self._pending_split_chapter_page = (
            _first_page(item)
            if item is not None
            and re.fullmatch(
                r"chapter\s+\d+[.:)]?",
                text.strip(),
                re.IGNORECASE,
            )
            else None
        )
        if item is not None and _effective_raw_label(item) == "section_header":
            self._set_hierarchy_base(item)

    def _set_hierarchy_base(self, item: dict[str, Any]) -> None:
        level = (item.get("meta") or {}).get("hf__heading_level")
        if isinstance(level, int):
            self._hierarchy_base_level = min(5, max(1, level))

    def _infer_lower_level(self, item: dict[str, Any]) -> int:
        text = str(item.get("text", "")).strip()
        numbered = re.match(r"^(\d+(?:\.\d+){1,4})[.)]?\s+\S", text)
        if numbered:
            return min(5, 2 + numbered.group(1).count("."))

        metadata = item.get("meta") or {}
        hierarchy_level = metadata.get("hf__heading_level")
        if isinstance(hierarchy_level, int):
            if self._hierarchy_base_level is not None:
                return min(
                    5,
                    max(2, hierarchy_level - self._hierarchy_base_level + 1),
                )
            return min(5, max(2, hierarchy_level))

        font_size = metadata.get("hf__heading_font_size")
        if isinstance(font_size, (int, float)):
            normalized_size = round(float(font_size), 3)
            if self.h2_font_floor is not None and normalized_size >= self.h2_font_floor:
                return 3
            resolved = self.lower_level_by_size.get(normalized_size)
            if resolved is not None:
                return resolved

        hierarchy_level = metadata.get("hf__heading_level")
        if isinstance(hierarchy_level, int):
            return min(5, max(3, hierarchy_level))
        level = item.get("level")
        if isinstance(level, int):
            return min(5, max(3, level))
        return 3

    def _discover_chapter_outlines(
        self,
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> None:
        chapter_starts: list[tuple[int, str, str, int]] = []
        for index, reference in enumerate(ordered_references):
            title_item = all_items.get(reference)
            if not title_item or reference == self.main_title_ref:
                continue

            raw_label = _effective_raw_label(title_item)
            title = str(title_item.get("text", "")).strip()
            chapter_key = self._chapter_key(title)
            title_page = self._item_page(title_item, all_items)
            if not chapter_key or title_page is None:
                continue

            is_explicit_title = raw_label == "title"
            is_inferred_title = raw_label == "section_header" and (
                self._is_named_back_matter_chapter(title)
                or self._has_matching_chapter_heading(
                    chapter_key,
                    title_page,
                    index,
                    all_items,
                    ordered_references,
                )
            )
            if not is_explicit_title and not is_inferred_title:
                continue

            self.chapter_title_refs.add(reference)
            chapter_starts.append((index, reference, chapter_key, title_page))

        for index, _, chapter_key, title_page in chapter_starts:
            candidates: list[tuple[str, dict[str, Any]]] = []
            container_children: dict[str, set[str]] = {}
            for candidate_reference in ordered_references[index + 1 :]:
                candidate = all_items.get(candidate_reference)
                if not candidate:
                    continue
                if candidate_reference in self.chapter_title_refs:
                    break
                candidate_page = self._item_page(candidate, all_items)
                if candidate_page is not None and candidate_page > title_page:
                    break
                if candidate_page != title_page:
                    continue

                raw_label = _effective_raw_label(candidate)
                if raw_label in {"list", "form_area", "key_value_area", "group"}:
                    child_refs = [
                        str(child.get("$ref", ""))
                        for child in candidate.get("children", [])
                        if str(child.get("$ref", ""))
                    ]
                    container_children[candidate_reference] = set(child_refs)
                    candidates.extend(
                        (child_reference, child_item)
                        for child_reference in child_refs
                        if (child_item := all_items.get(child_reference)) is not None
                    )
                elif raw_label in {"list_item", "text"}:
                    candidates.append((candidate_reference, candidate))

            headings, consumed_refs = self._chapter_contents_entries(candidates)
            outline = {
                self._chapter_key(heading)
                for heading in headings
                if self._chapter_key(heading)
            }
            self.chapter_contents_refs.update(consumed_refs)
            for container_reference, child_refs in container_children.items():
                if child_refs & consumed_refs:
                    self.chapter_contents_refs.add(container_reference)
            self.chapter_outlines[chapter_key] = outline

    def _has_matching_chapter_heading(
        self,
        chapter_key: str,
        title_page: int,
        start_index: int,
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> bool:
        for reference in ordered_references[start_index + 1 :]:
            item = all_items.get(reference)
            if not item:
                continue
            page = self._item_page(item, all_items)
            if page is not None and page > title_page + 2:
                return False
            if _effective_raw_label(item) == "section_header" and self._is_numbered_chapter(
                str(item.get("text", ""))
            ):
                return self._chapter_key(str(item.get("text", ""))) == chapter_key
        return False

    @classmethod
    def _chapter_contents_entries(
        cls,
        candidates: list[tuple[str, dict[str, Any]]],
    ) -> tuple[list[str], set[str]]:
        headings: list[str] = []
        consumed_refs: set[str] = set()
        pending_page_ref: str | None = None

        for reference, item in candidates:
            raw_label = _effective_raw_label(item)
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            if not text or raw_label not in {"list_item", "text"}:
                pending_page_ref = None
                continue

            heading = cls._chapter_contents_heading(text)
            if heading:
                headings.append(heading)
                consumed_refs.add(reference)
                if pending_page_ref is not None:
                    consumed_refs.add(pending_page_ref)
                    pending_page_ref = None
                continue

            if cls._is_page_marker(text):
                pending_page_ref = reference
                continue

            if pending_page_ref is not None and len(text) <= 250:
                headings.append(text.strip(" .–—-"))
                consumed_refs.update({pending_page_ref, reference})
            pending_page_ref = None

        return headings, consumed_refs

    def _build_lower_style_levels(self, all_items: dict[str, dict[str, Any]]) -> None:
        chapter_keys = set(self.chapter_outlines)
        outline_keys = {
            heading
            for headings in self.chapter_outlines.values()
            for heading in headings
        }
        h2_sizes = [
            round(float(font_size), 3)
            for item in all_items.values()
            if (
                _effective_raw_label(item) == "section_header"
                and self._chapter_key(str(item.get("text", ""))) in outline_keys
                and isinstance(
                    font_size := (item.get("meta") or {}).get("hf__heading_font_size"),
                    (int, float),
                )
            )
        ]
        self.h2_font_floor = min(h2_sizes) if h2_sizes else None
        sizes: set[float] = set()
        for item in all_items.values():
            if _effective_raw_label(item) != "section_header":
                continue
            key = self._chapter_key(str(item.get("text", "")))
            if key in chapter_keys or key in outline_keys:
                continue
            font_size = (item.get("meta") or {}).get("hf__heading_font_size")
            if isinstance(font_size, (int, float)):
                normalized_size = round(float(font_size), 3)
                if self.h2_font_floor is None or normalized_size < self.h2_font_floor:
                    sizes.add(normalized_size)

        for index, font_size in enumerate(sorted(sizes, reverse=True)):
            self.lower_level_by_size[font_size] = min(5, 3 + index)

    @staticmethod
    def _item_page(
        item: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
    ) -> int | None:
        provenance = item.get("prov") or []
        if provenance:
            return int(provenance[0].get("page_no", 1))
        for child in item.get("children", []):
            child_item = all_items.get(str(child.get("$ref", "")))
            if child_item and child_item.get("prov"):
                return _first_page(child_item)
        return None

    @staticmethod
    def _chapter_contents_heading(value: str) -> str | None:
        normalized = re.sub(r"\s+", " ", value).strip()
        match = re.match(
            r"^(?:p(?:age)?\.?\s*)?(?:\d+|[ivxlcdm]+)\s+(.+?)$",
            normalized,
            re.IGNORECASE,
        )
        if not match:
            return None
        heading = re.sub(r"\.{2,}\s*(?:\d+|[ivxlcdm]+)?$", "", match.group(1)).strip(
            " .–—-"
        )
        return heading if heading and len(heading) <= 250 else None

    @staticmethod
    def _is_page_marker(value: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:p(?:age)?\.?\s*)?(?:\d+|[ivxlcdm]+)",
                value.strip(),
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _chapter_key(value: str) -> str:
        without_number = re.sub(
            r"^(?:chapter\s+)?\d+[.:)]?\s*",
            "",
            value.strip(),
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", without_number).strip(" .–—-").casefold()

    @staticmethod
    def _is_numbered_chapter(value: str) -> bool:
        return bool(
            re.match(
                r"^(?:chapter\s+\d+[.:)]?(?:\s+\S.*)?|\d+\.\s+\S)",
                value.strip(),
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _is_named_back_matter_chapter(value: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:appendix(?:\s+[a-z0-9ivxlcdm]+)?|appendices|"
                r"bibliography|glossary|references|"
                r"acknowledg(?:e)?ments)",
                value.strip(),
                re.IGNORECASE,
            )
        )


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
        stage(1, "Docling is extracting text, layout and tables")
        raw_document, blocks, doc_confidence, warnings = self._run_docling(pdf_path)

        stage(4, "Applying metadata rules to Docling text from pages 1–8")
        try:
            metadata_payload = extract_metadata_from_docling(
                raw_document,
                pdf_path,
                self.settings,
            )
        except Exception as exc:
            warnings.append(f"Rule-based metadata extraction failed: {exc}")
            metadata_payload = empty_metadata_payload(self.settings)

        stage(5, "Scoring confidence and creating the review queue")
        review_items = self._build_review_items(blocks)
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
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[str]]:
        converter = self._get_docling_converter()
        with self._docling_lock:
            result = converter.convert(pdf_path)
        hierarchy = apply_hierarchy(result, pdf_path)
        raw_document = result.document.export_to_dict()
        attach_hierarchy_metadata(raw_document, hierarchy)
        warnings = list(hierarchy.warnings)
        warnings.extend(annotate_pdf_artifacts(raw_document, pdf_path))
        callout_regions, callout_warnings = detect_callout_regions(pdf_path)
        warnings.extend(callout_warnings)
        cluster_confidences = self._cluster_confidences(result)
        confidence_by_ref = self._confidence_by_reference(
            raw_document, cluster_confidences
        )
        blocks = self._blocks_from_document(raw_document, confidence_by_ref)
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
                    PdfPipelineOptions,
                    TableStructureOptions,
                )
                from docling.document_converter import (
                    DocumentConverter,
                    PdfFormatOption,
                )
            except ImportError as exc:
                raise RuntimeError(
                    'Docling dependencies are missing. Install the backend with: pip install -e "./backend[docling]"'
                ) from exc

            options = PdfPipelineOptions()
            options.do_ocr = self.settings.do_ocr
            options.do_table_structure = self.settings.do_table_structure
            options.table_structure_options = TableStructureOptions(
                do_cell_matching=True
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
    ) -> list[dict[str, Any]]:
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
        resolver = HeadingResolver(
            self._main_title_reference(all_items, ordered_references),
            all_items,
            ordered_references,
        )
        blocks: list[dict[str, Any]] = []
        consumed: set[str] = set()

        def visit(reference: str) -> None:
            item = all_items.get(reference)
            if not item or reference in consumed:
                return
            consumed.add(reference)
            raw_label = _effective_raw_label(item)
            children = [
                str(child.get("$ref", "")) for child in item.get("children", [])
            ]

            if (item.get("meta") or {}).get("konverter_exclude_from_output"):
                for child in children:
                    visit(child)
                return

            if resolver.is_chapter_contents(reference):
                consumed.update(child for child in children if child)
                return

            if raw_label == "list" and children:
                child_items = [all_items.get(child) for child in children]
                child_items = [child for child in child_items if child]
                consumed.update(child for child in children if child)
                list_entries = []
                for child in child_items:
                    value = str(child.get("text", "")).strip()
                    marker = str(child.get("marker", "")).strip()
                    list_entries.append(
                        {
                            "text": value,
                            "marker": marker,
                            "enumerated": bool(child.get("enumerated")),
                        }
                    )
                list_texts = [entry["text"] for entry in list_entries]
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
                        "list_items": [value for value in list_texts if value],
                        "list_entries": [
                            entry for entry in list_entries if entry["text"]
                        ],
                        "page": _first_page(child_items[0]) if child_items else 1,
                        "confidence": min(valid_confidences)
                        if valid_confidences
                        else None,
                        "source_bounds": self._combined_source_bounds(
                            document, child_items
                        ),
                    }
                )
                return

            if raw_label in {"form_area", "key_value_area"} and children:
                child_items = [all_items.get(child) for child in children]
                child_items = [child for child in child_items if child]
                consumed.update(child for child in children if child)
                text = "\n".join(
                    str(child.get("text", "")).strip() for child in child_items
                )
                blocks.append(
                    {
                        "id": reference,
                        "label": "form",
                        "text": text,
                        "page": _first_page(child_items[0]) if child_items else 1,
                        "confidence": None,
                        "source_bounds": self._combined_source_bounds(
                            document, child_items
                        ),
                    }
                )
                return

            if raw_label in {"table", "document_index"}:
                table = self._table_data(item)
                blocks.append(
                    {
                        "id": reference,
                        "label": "document_index"
                        if raw_label == "document_index"
                        else "table",
                        "text": _plain_text_from_table(table),
                        "table_data": table,
                        "page": _first_page(item),
                        "confidence": confidence_by_ref.get(reference),
                        "source_bounds": self._combined_source_bounds(document, [item]),
                    }
                )
                return

            if raw_label == "group":
                for child in children:
                    visit(child)
                return

            label = resolver.label_for(item)
            text = str(item.get("text", "")).strip()
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
            if raw_label in {"section_header", "title"}:
                for child in children:
                    visit(child)

        for child in document.get("body", {}).get("children", []):
            visit(str(child.get("$ref", "")))

        leftovers = [
            item
            for reference, item in all_items.items()
            if reference not in consumed and item.get("prov")
        ]
        leftovers.sort(
            key=lambda item: (
                _first_page(item),
                float((item.get("prov") or [{}])[0].get("bbox", {}).get("t", 0)),
                float((item.get("prov") or [{}])[0].get("bbox", {}).get("l", 0)),
            )
        )
        for item in leftovers:
            visit(str(item.get("self_ref", "")))

        ordered_blocks = [
            {**block, "order": index}
            for index, block in enumerate(blocks)
            if block["label"] not in {"header", "footer"} or block.get("text")
        ]
        ordered_blocks = self._merge_split_chapter_titles(ordered_blocks)
        if not any(block["label"] == "title" for block in ordered_blocks):
            source_name = (
                str(document.get("name", "Document")).replace("_", " ").strip()
            )
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
            for index, block in enumerate(ordered_blocks):
                block["order"] = index
        return ordered_blocks

    @staticmethod
    def _merge_split_chapter_titles(
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Join ``Chapter N`` and its same-page subtitle into one section title."""
        merged: list[dict[str, Any]] = []
        for block in blocks:
            if block.get("label") != "chapter_title_continuation":
                merged.append(block)
                continue
            previous = merged[-1] if merged else None
            if (
                previous is not None
                and previous.get("label") == "chapter_title"
                and int(previous.get("page", 1)) == int(block.get("page", 1))
            ):
                number = str(previous.get("text", "")).rstrip(" .:–—-")
                subtitle = str(block.get("text", "")).strip()
                previous["text"] = f"{number}: {subtitle}" if subtitle else number
                previous["confidence"] = min(
                    value
                    for value in (
                        previous.get("confidence"),
                        block.get("confidence"),
                        1.0,
                    )
                    if value is not None
                )
                continue
            block["label"] = "section_header_2"
            merged.append(block)
        for index, block in enumerate(merged):
            block["order"] = index
        return merged

    @staticmethod
    def _ordered_document_references(
        document: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Return depth-first reading order after hierarchy reconstruction."""
        ordered: list[str] = []
        seen: set[str] = set()

        def collect(reference: str) -> None:
            if not reference or reference in seen:
                return
            seen.add(reference)
            ordered.append(reference)
            item = all_items.get(reference)
            if not item:
                return
            for child in item.get("children", []):
                collect(str(child.get("$ref", "")))

        for child in document.get("body", {}).get("children", []):
            collect(str(child.get("$ref", "")))
        return ordered

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
            str(page),
            document.get("pages", {}).get(page, {}),
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
        """Choose one early cover title; later Docling titles are chapters."""
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
            if not item:
                continue
            if (item.get("meta") or {}).get("konverter_exclude_from_output"):
                continue
            raw_label = _effective_raw_label(item)
            if raw_label not in {"title", "section_header"}:
                continue
            page = _first_page(item)
            text = str(item.get("text", "")).strip()
            if page > 5 or not text or excluded.search(text) or address.search(text):
                continue
            metadata = item.get("meta") or {}
            font_size = metadata.get("hf__heading_font_size")
            score = (
                float(font_size) * 10 if isinstance(font_size, (int, float)) else 0.0
            )
            if raw_label == "title":
                score += 1000
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
                    "status": "pending",
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
