from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# No imports from backend.app here: this module is copied verbatim into the
# GPU worker image, so it must stay self-contained. Docling imports must stay
# lazy (inside functions) since the CPU-only pod never installs docling/torch.

# Docling's DocumentConverter holds multi-hundred-MB to multi-GB PyTorch, ONNX,
# RapidOCR, and pypdfium2 model state and is not thread-safe for concurrent
# convert() calls. Serialising converter creation and conversion under _lock
# prevents OOM under KONVERTER_WORKERS > 1 and avoids concurrent pypdfium2/torch
# state corruption while post-Docling stages continue concurrently.
_lock = threading.Lock()
_converter_cache: dict[tuple[bool, bool, str, str, float | None], Any] = {}


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    raw = value.value if hasattr(value, "value") else value
    text = str(raw).strip()
    return text or None


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_table_mode(raw: Any) -> str:
    if raw is None:
        return "accurate"
    candidate = _enum_value(raw)
    mode = (candidate or "").lower()
    if mode not in {"accurate", "fast"}:
        raise ValueError(f"table_mode must be 'accurate' or 'fast', got {raw!r}")
    return mode


def _normalize_timeout(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError(f"document_timeout must be a positive finite number or None, got {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"document_timeout must be a positive finite number or None, got {raw!r}"
        ) from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"document_timeout must be a positive finite number or None, got {raw!r}"
        )
    return value


def _serialize_errors(errors: Any) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for err in errors or []:
        raw_page = getattr(err, "page_no", None)
        page_no = (
            int(raw_page)
            if raw_page is not None and not isinstance(raw_page, bool)
            else None
        )
        serialized.append(
            {
                "component_type": _enum_value(getattr(err, "component_type", None))
                or "unknown",
                "module_name": str(getattr(err, "module_name", "") or ""),
                "error_message": str(getattr(err, "error_message", "") or ""),
                "category": _enum_value(getattr(err, "category", None)) or "unknown",
                "page_no": page_no,
            }
        )
    return serialized


def run_docling(
    pdf_path: Path,
    options: dict[str, Any] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Parse a PDF with Docling and return JSON-serialisable results.

    options: {
        "do_ocr": bool,
        "do_table_structure": bool,
        "device": "cpu"|"cuda"|"auto",
        "table_mode": "accurate"|"fast",
        "document_timeout": float | None,
    }
    returns: {
        "raw_docling": dict,
        "cluster_confidences": list,
        "doc_confidence": dict,
        "docling_version": str,
        "conversion_status": str,
        "conversion_errors": list[dict],
        "parse_elapsed_seconds": float,
    }
    """
    opts = options or {}
    if cancel_check is not None and cancel_check():
        raise InterruptedError("Processing was stopped")

    converter = _get_converter(opts, cancel_check=cancel_check)
    with _lock:
        if cancel_check is not None and cancel_check():
            raise InterruptedError("Processing was stopped")
        parse_started = time.monotonic()
        result = converter.convert(pdf_path)
        parse_elapsed_seconds = time.monotonic() - parse_started

    raw_status = getattr(result, "status", None)
    conversion_status = (_enum_value(raw_status) or "success").lower()
    conversion_errors = _serialize_errors(getattr(result, "errors", None))
    failed_pages = sorted(
        {err["page_no"] for err in conversion_errors if err["page_no"] is not None}
    )

    if conversion_status == "failure" or conversion_status not in {
        "success",
        "partial_success",
    }:
        detail = "; ".join(
            err["error_message"] for err in conversion_errors[:3] if err["error_message"]
        )
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"Docling conversion failed with status '{conversion_status}'{suffix}"
        )

    document = getattr(result, "document", None)
    raw_docling = document.export_to_dict() if document is not None else None
    if not isinstance(raw_docling, dict) or not raw_docling.get("pages"):
        raise RuntimeError("Docling conversion produced no pages.")

    try:
        import docling

        docling_version = str(getattr(docling, "__version__", "unknown"))
    except ImportError:
        docling_version = "unknown"

    cluster_confidences = _cluster_confidences(result)
    confidence = getattr(result, "confidence", None)
    doc_confidence = {
        "layout_score": _finite_float(getattr(confidence, "layout_score", None)),
        "mean_score": _finite_float(getattr(confidence, "mean_score", None)),
        "mean_grade": _enum_value(getattr(confidence, "mean_grade", None)),
        "ocr_score": _finite_float(getattr(confidence, "ocr_score", None)),
        "table_score": _finite_float(getattr(confidence, "table_score", None)),
        "parse_score": _finite_float(getattr(confidence, "parse_score", None)),
        "conversion_status": conversion_status,
        "error_count": len(conversion_errors),
        "failed_pages": failed_pages,
    }
    return {
        "raw_docling": raw_docling,
        "cluster_confidences": cluster_confidences,
        "doc_confidence": doc_confidence,
        "docling_version": docling_version,
        "conversion_status": conversion_status,
        "conversion_errors": conversion_errors,
        "parse_elapsed_seconds": parse_elapsed_seconds,
    }


def _get_converter(
    options: dict[str, Any],
    cancel_check: Callable[[], bool] | None = None,
) -> Any:
    raw_device = options.get("device", "cpu")
    device = str(raw_device if raw_device is not None else "cpu").strip().lower() or "cpu"
    key = (
        bool(options.get("do_ocr")),
        bool(options.get("do_table_structure")),
        device,
        _normalize_table_mode(options.get("table_mode")),
        _normalize_timeout(options.get("document_timeout")),
    )
    converter = _converter_cache.get(key)
    if converter is not None:
        return converter
    with _lock:
        converter = _converter_cache.get(key)
        if converter is not None:
            return converter
        if cancel_check is not None and cancel_check():
            raise InterruptedError("Processing was stopped")
        converter = _build_converter(*key)
        _converter_cache[key] = converter
        return converter


def _build_converter(
    do_ocr: bool,
    do_table_structure: bool,
    device: str,
    table_mode: str = "accurate",
    document_timeout: float | None = None,
) -> Any:
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
            TableFormerMode,
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
        do_cell_matching=True,
        mode=TableFormerMode.FAST if table_mode == "fast" else TableFormerMode.ACCURATE,
    )
    if document_timeout is not None:
        pipeline_options.document_timeout = document_timeout
    pipeline_options.generate_parsed_pages = True
    pipeline_options.heading_hierarchy_options = HeadingHierarchyOptions(
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
    for page in getattr(result, "pages", []) or []:
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
                    _finite_float(getattr(cluster, "confidence", None)),
                ]
            )
    return clusters
