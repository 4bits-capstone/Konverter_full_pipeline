"""Adapter between docling-hierarchical-pdf and Konverter's flat block schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class HierarchyAnnotations:
    original_labels: dict[str, str] = field(default_factory=dict)
    levels: dict[str, int] = field(default_factory=dict)
    styles: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def apply_hierarchy(
    result: Any,
    source_path: Path,
    *,
    package_only: bool = False,
) -> HierarchyAnnotations:
    """Run hierarchy reconstruction and retain evidence needed by review/export.

    ``package_only`` uses ``docling-hierarchical-pdf``'s own postprocessor.  The
    default keeps Konverter's guarded adapter, after which the rule-based
    resolver can use the annotations together with chapter-opening contents.
    """
    annotations = HierarchyAnnotations()
    for item, _ in result.document.iterate_items():
        label = getattr(item, "label", "unspecified")
        annotations.original_labels[item.self_ref] = str(
            label.value if hasattr(label, "value") else label
        )

    try:
        from hierarchical.hierarchy_builder import create_toc

        from .hierarchy_postprocessor import flatten_hierarchy_tree

        if package_only:
            from hierarchical.postprocessor import ResultPostprocessor
        else:
            from .hierarchy_postprocessor import ResultPostprocessor
    except ImportError as exc:
        annotations.warnings.append(
            "Heading hierarchy package unavailable; used Konverter rule fallback "
            f"({exc})."
        )
        return annotations

    postprocessor = ResultPostprocessor(result, source=source_path)
    try:
        headers = postprocessor.get_headers()
        style_tree = create_toc(headers)
        style_levels = {
            node.doc_ref: min(5, max(1, level))
            for node, level in flatten_hierarchy_tree(style_tree)
            if node.doc_ref
        }
        for header in headers:
            reference = str(header.get("reference", ""))
            if reference:
                annotations.styles[reference] = {
                    "font_size": header.get("font_size"),
                    "is_bold": bool(header.get("is_bold")),
                    "is_italic": bool(header.get("is_italic")),
                    "font": str(header.get("font", "")),
                }
        postprocessor.process()
    except Exception as exc:  # keep document processing available on unusual PDFs
        annotations.warnings.append(
            f"Hierarchy reconstruction failed; used Konverter rule fallback ({exc})."
        )
        return annotations

    for item, _ in result.document.iterate_items():
        level = getattr(item, "level", None)
        if isinstance(level, int):
            annotations.levels[item.self_ref] = min(5, max(1, level))
    for reference, level in style_levels.items():
        annotations.levels.setdefault(reference, level)
    return annotations


def attach_hierarchy_metadata(
    document: dict[str, Any],
    annotations: HierarchyAnnotations,
) -> None:
    """Store resolved hierarchy signals without changing Docling's public labels."""
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
            if not reference:
                continue
            metadata = item.setdefault("meta", {})
            original = annotations.original_labels.get(reference)
            if original:
                metadata["konverter_original_label"] = original
            level = annotations.levels.get(reference)
            if level is not None:
                metadata["hf__heading_level"] = level
            style = annotations.styles.get(reference)
            if style:
                metadata["hf__heading_font_size"] = style.get("font_size")
                metadata["hf__heading_is_bold"] = style.get("is_bold")
                metadata["hf__heading_is_italic"] = style.get("is_italic")
                metadata["hf__heading_font"] = style.get("font")
