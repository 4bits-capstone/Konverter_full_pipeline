from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

# No imports from backend.app here: this module is copied verbatim into the
# GPU worker image, so it must stay self-contained. Docling imports must stay
# lazy (inside functions) since the CPU-only pod never installs docling/torch.

_lock = threading.Lock()
_converter_cache: dict[tuple[bool, bool, str], Any] = {}

# Docling's built-in heading-hierarchy stage restores SectionHeaderItem.level from three
# signals it reads out of the document itself -- no extra model, nothing to download -- in
# precedence order: PDF bookmarks, then the heading's leading numbering marker, then its
# visual style. The layout model only flags a region as a header, so without the stage every
# heading arrives at level 1 and a document whose real structure runs PART I -> 1. ->
# 1.1 -> (a) is flattened. Konverter only renders H1-H5, so deeper levels are clamped to 5.
#
# The option model gained fields over time: newer docling releases add use_font_style and
# style_size_tolerance, which refine the style fallback with font weight, slant and letter
# case. We build the options against the fields the installed docling actually exposes, so a
# pinned worker and a newer local install each get the strongest configuration they support
# instead of failing on an unknown field.
_HEADING_HIERARCHY_OPTIONS: dict[str, Any] = {
    "enabled": True,
    "use_bookmarks": True,
    "use_numbering": True,
    "use_style": True,
    "use_font_style": True,
    "style_size_tolerance": 0.05,
    "max_level": 5,
    "bookmark_match_threshold": 0.76,
}


def heading_hierarchy_option_kwargs(
    supported_fields: set[str] | None = None,
) -> dict[str, Any]:
    """The documented heading-hierarchy options, filtered to the installed docling's fields.

    ``supported_fields`` is the field-name set of the installed ``HeadingHierarchyOptions``
    (``HeadingHierarchyOptions.model_fields``). When ``None``, every documented option is
    returned; otherwise options the installed version does not know are dropped so the stage
    still runs with its core signals on older pins.
    """
    if supported_fields is None:
        return dict(_HEADING_HIERARCHY_OPTIONS)
    return {
        name: value
        for name, value in _HEADING_HIERARCHY_OPTIONS.items()
        if name in supported_fields
    }


def heading_hierarchy_options(options_cls: Any) -> Any:
    """Instantiate ``HeadingHierarchyOptions`` for the installed docling version."""
    fields = getattr(options_cls, "model_fields", None) or getattr(
        options_cls, "__fields__", None
    )
    supported = set(fields) if fields else None
    return options_cls(**heading_hierarchy_option_kwargs(supported))


def run_docling(pdf_path: Path, options: dict[str, Any]) -> dict[str, Any]:
    """Parse a PDF with Docling and return JSON-serialisable results.

    options: {"do_ocr": bool, "do_table_structure": bool, "device": "cpu"|"cuda"|"auto"}
    returns: {"raw_docling": dict, "cluster_confidences": list, "doc_confidence": dict,
              "docling_version": str}
    """
    converter = _get_converter(options)
    with _lock:
        result = converter.convert(pdf_path)

    import docling

    raw_docling = result.document.export_to_dict()
    cluster_confidences = _cluster_confidences(result)
    confidence = getattr(result, "confidence", None)
    doc_confidence = {
        "layout_score": getattr(confidence, "layout_score", None),
        "mean_score": getattr(confidence, "mean_score", None),
        "mean_grade": str(getattr(confidence, "mean_grade", "")) or None,
        "ocr_score": getattr(confidence, "ocr_score", None),
        "table_score": getattr(confidence, "table_score", None),
        "parse_score": getattr(confidence, "parse_score", None),
    }
    return {
        "raw_docling": raw_docling,
        "cluster_confidences": cluster_confidences,
        "doc_confidence": doc_confidence,
        "docling_version": docling.__version__,
    }


def _get_converter(options: dict[str, Any]) -> Any:
    key = (
        bool(options.get("do_ocr")),
        bool(options.get("do_table_structure")),
        str(options.get("device", "cpu")),
    )
    converter = _converter_cache.get(key)
    if converter is not None:
        return converter
    with _lock:
        converter = _converter_cache.get(key)
        if converter is not None:
            return converter
        converter = _build_converter(*key)
        _converter_cache[key] = converter
        return converter


def _build_converter(do_ocr: bool, do_table_structure: bool, device: str) -> Any:
    try:
        from docling.datamodel.settings import settings as docling_settings

        docling_settings.inference.compile_torch_models = False
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
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise RuntimeError(
            'Docling dependencies are missing or outdated. Install with: pip install -e "./backend[docling]"'
        ) from exc

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = do_ocr
    pipeline_options.do_table_structure = do_table_structure
    pipeline_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True
    )
    pipeline_options.generate_parsed_pages = True
    pipeline_options.heading_hierarchy_options = heading_hierarchy_options(
        HeadingHierarchyOptions
    )
    named_devices = {
        name: getattr(AcceleratorDevice, name.upper(), name)
        for name in ("auto", "cpu", "cuda", "mps", "xpu")
    }
    pipeline_options.accelerator_options = AcceleratorOptions(
        device=named_devices.get(device, device),
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            )
        }
    )


def _cluster_confidences(result: Any) -> list[list[Any]]:
    clusters: list[list[Any]] = []
    for page in result.pages:
        layout = getattr(getattr(page, "predictions", None), "layout", None)
        for cluster in getattr(layout, "clusters", []) if layout else []:
            bbox = cluster.bbox
            clusters.append(
                [
                    int(page.page_no),
                    {
                        "l": float(bbox.l),
                        "t": float(bbox.t),
                        "r": float(bbox.r),
                        "b": float(bbox.b),
                    },
                    float(cluster.confidence),
                ]
            )
    return clusters
