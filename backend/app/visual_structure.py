"""Detect decorative PDF artifacts and editorial callout panels."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _normalise_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _rgb(value: int) -> tuple[int, int, int]:
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def _span_is_artifact(
    text: str,
    size: float,
    rgb: tuple[int, int, int],
    alpha: float,
    direction: tuple[float, float],
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
) -> bool:
    word_count = len(text.split())
    box_width = max(0.0, bbox[2] - bbox[0])
    box_height = max(0.0, bbox[3] - bbox[1])
    area_ratio = (box_width * box_height) / max(page_width * page_height, 1.0)
    luminance = sum(rgb) / (255 * 3)
    rotated = abs(direction[1]) > 0.17

    return bool(
        alpha < 0.58
        or (rotated and size >= 20 and word_count <= 8)
        or (size >= 110 and word_count <= 10)
        or (area_ratio >= 0.075 and word_count <= 8)
        or (luminance >= 0.86 and size >= 34 and word_count <= 8)
        or (bbox[0] < 2 and size >= 22 and word_count <= 2)
    )


def _bbox_overlap_ratio(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    left = max(first["left"], second["left"])
    top = max(first["top"], second["top"])
    right = min(first["right"], second["right"])
    bottom = min(first["bottom"], second["bottom"])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first["right"] - first["left"]) * max(
        0.0, first["bottom"] - first["top"]
    )
    return intersection / first_area if first_area else 0.0


def _top_left_provenance_bbox(
    provenance: dict[str, Any],
    page_height: float,
) -> dict[str, float] | None:
    bbox = provenance.get("bbox")
    if not bbox:
        return None
    left = float(bbox.get("l", 0))
    right = float(bbox.get("r", 0))
    top = float(bbox.get("t", 0))
    bottom = float(bbox.get("b", 0))
    if str(bbox.get("coord_origin", "")).upper().endswith("BOTTOMLEFT"):
        top, bottom = page_height - top, page_height - bottom
    return {
        "left": min(left, right),
        "top": min(top, bottom),
        "right": max(left, right),
        "bottom": max(top, bottom),
    }


def annotate_pdf_artifacts(
    document: dict[str, Any],
    pdf_path: Path,
) -> list[str]:
    """Mark watermark/decorative text so it is excluded before block export."""
    try:
        import fitz
    except ImportError:
        return ["PyMuPDF unavailable; decorative PDF artifact filtering was skipped."]

    suspicious: dict[int, list[dict[str, Any]]] = defaultdict(list)
    repeated: Counter[tuple[int, str]] = Counter()
    try:
        pdf = fitz.open(pdf_path)
        for page_index, page in enumerate(pdf):
            page_number = page_index + 1
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    direction = tuple(line.get("dir", (1.0, 0.0)))
                    for span in line.get("spans", []):
                        text = re.sub(r"\s+", " ", span.get("text", "")).strip()
                        if not text:
                            continue
                        repeated[(page_number, _normalise_text(text))] += 1
                        color = _rgb(int(span.get("color", 0)))
                        alpha = float(span.get("alpha", 255)) / 255
                        size = float(span.get("size", 0))
                        bbox = tuple(float(value) for value in span.get("bbox", (0, 0, 0, 0)))
                        if _span_is_artifact(
                            text,
                            size,
                            color,
                            alpha,
                            direction,
                            bbox,
                            page_width,
                            page_height,
                        ):
                            suspicious[page_number].append(
                                {
                                    "text": _normalise_text(text),
                                    "bounds": {
                                        "left": bbox[0],
                                        "top": bbox[1],
                                        "right": bbox[2],
                                        "bottom": bbox[3],
                                    },
                                }
                            )
    except Exception as exc:
        return [f"Decorative PDF artifact filtering failed ({exc})."]

    page_sizes = document.get("pages", {})
    for item in document.get("texts", []):
        provenance = item.get("prov") or []
        if not provenance:
            continue
        text = _normalise_text(item.get("text"))
        repeated_fragment = False
        matched_span = False
        outside_page = False
        for source in provenance:
            page_number = int(source.get("page_no", 1))
            page_meta = page_sizes.get(
                str(page_number), page_sizes.get(page_number, {})
            )
            page_width = float(page_meta.get("size", {}).get("width", 0))
            page_height = float(page_meta.get("size", {}).get("height", 0))
            bounds = _top_left_provenance_bbox(source, page_height)
            if bounds is None:
                continue
            outside_page = outside_page or bool(
                page_width > 0
                and page_height > 0
                and (
                    bounds["left"] < -3
                    or bounds["top"] < -3
                    or bounds["right"] > page_width + 3
                    or bounds["bottom"] > page_height + 3
                )
            )
            repeated_fragment = repeated_fragment or bool(
                repeated[(page_number, text)] >= 3 and len(text) <= 60
            )
            matched_span = matched_span or any(
                (
                    candidate["text"] == text
                    or candidate["text"] in text
                    or text in candidate["text"]
                )
                and _bbox_overlap_ratio(bounds, candidate["bounds"]) >= 0.45
                for candidate in suspicious.get(page_number, [])
                if candidate["text"] and text
            )
        if outside_page or repeated_fragment or matched_span:
            metadata = item.setdefault("meta", {})
            metadata["konverter_exclude_from_output"] = True
            metadata["konverter_exclusion_reason"] = (
                "text positioned outside the visible PDF page"
                if outside_page
                else (
                    "repeated decorative fragment"
                    if repeated_fragment
                    else "watermark or decorative background text"
                )
            )
    return []


def _rects_connect(first: dict[str, float], second: dict[str, float]) -> bool:
    horizontal_overlap = max(
        0.0,
        min(first["right"], second["right"]) - max(first["left"], second["left"]),
    )
    minimum_width = min(
        first["right"] - first["left"],
        second["right"] - second["left"],
    )
    vertical_gap = max(
        0.0,
        max(first["top"], second["top"]) - min(first["bottom"], second["bottom"]),
    )
    return minimum_width > 0 and horizontal_overlap / minimum_width >= 0.72 and vertical_gap <= 7


def _merge_rectangles(rectangles: list[dict[str, float]]) -> list[dict[str, float]]:
    groups: list[dict[str, float]] = []
    for rectangle in sorted(rectangles, key=lambda value: (value["top"], value["left"])):
        matching = next(
            (group for group in groups if _rects_connect(group, rectangle)),
            None,
        )
        if matching is None:
            groups.append(dict(rectangle))
        else:
            matching["left"] = min(matching["left"], rectangle["left"])
            matching["top"] = min(matching["top"], rectangle["top"])
            matching["right"] = max(matching["right"], rectangle["right"])
            matching["bottom"] = max(matching["bottom"], rectangle["bottom"])
    return groups


def detect_callout_regions(pdf_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Find wide shaded panels made from one or more adjacent vector rectangles."""
    try:
        import fitz
    except ImportError:
        return [], ["PyMuPDF unavailable; visual callout detection was skipped."]

    regions: list[dict[str, Any]] = []
    try:
        pdf = fitz.open(pdf_path)
        for page_index, page in enumerate(pdf):
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            rectangles: list[dict[str, float]] = []
            for drawing in page.get_drawings():
                rect = drawing.get("rect")
                fill = drawing.get("fill")
                if rect is None or fill is None:
                    continue
                width = float(rect.width)
                height = float(rect.height)
                if width / page_width < 0.55 or height < 8:
                    continue
                if max(fill) - min(fill) > 0.12 or sum(fill) / 3 >= 0.98:
                    continue
                rectangles.append(
                    {
                        "left": float(rect.x0),
                        "top": float(rect.y0),
                        "right": float(rect.x1),
                        "bottom": float(rect.y1),
                    }
                )
            for merged in _merge_rectangles(rectangles):
                width = merged["right"] - merged["left"]
                height = merged["bottom"] - merged["top"]
                area_ratio = (width * height) / max(page_width * page_height, 1.0)
                if height >= 50 and area_ratio >= 0.045:
                    regions.append(
                        {
                            "page": page_index + 1,
                            **merged,
                            "page_width": page_width,
                            "page_height": page_height,
                        }
                    )
    except Exception as exc:
        return [], [f"Visual callout detection failed ({exc})."]
    return regions, []


def _block_in_region(block: dict[str, Any], region: dict[str, Any]) -> bool:
    if int(block.get("page", 1)) != int(region["page"]):
        return False
    bounds = block.get("source_bounds")
    if not bounds:
        return False
    center_x = (float(bounds["left"]) + float(bounds["right"])) / 2
    center_y = (float(bounds["top"]) + float(bounds["bottom"])) / 2
    return bool(
        region["left"] - 3 <= center_x <= region["right"] + 3
        and region["top"] - 3 <= center_y <= region["bottom"] + 3
    )


def _callout_kind(title: str) -> str:
    normalised = _normalise_text(title).strip("*! ")
    if re.match(r"^case\s+stud(?:y|ies)\b", normalised):
        return "case-study"
    if re.match(r"^recommendations?\b", normalised):
        return "recommendations"
    return "information"


def group_visual_callouts(
    blocks: list[dict[str, Any]],
    regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse each detected panel into one reviewable semantic callout block."""
    used: set[str] = set()
    replacements: dict[str, dict[str, Any]] = {}
    for region in regions:
        contained = [
            block
            for block in blocks
            if str(block.get("id", "")) not in used
            and not block.get("toc_derived")
            and block.get("label") not in {
                "title",
                "header",
                "footer",
                "document_index",
            }
            and _block_in_region(block, region)
        ]
        contained.sort(key=lambda block: int(block.get("order", 0)))
        heading_index = next(
            (
                index
                for index, block in enumerate(contained)
                if str(block.get("label", "")).startswith("section_header_")
                and 1 <= len(str(block.get("text", "")).split()) <= 12
            ),
            None,
        )
        if heading_index is None:
            continue
        contained = contained[heading_index:]
        if len(contained) < 2:
            continue

        heading = contained[0]
        raw_title = str(heading.get("text", "")).strip()
        title = re.sub(r"^[*!·•]+\s*", "", raw_title).strip()
        if not title:
            continue
        child_blocks = contained[1:]
        confidence_values = [
            float(block["confidence"])
            for block in contained
            if block.get("confidence") is not None
        ]
        box_section = {
            "id": f"box-section:{heading['id']}",
            "label": "box_section",
            "text": "\n\n".join(
                str(block.get("text", "")).strip()
                for block in child_blocks
                if str(block.get("text", "")).strip()
            ),
            "box_section_title": title,
            "box_section_kind": _callout_kind(title),
            "box_section_blocks": child_blocks,
            "page": int(region["page"]),
            "confidence": min(confidence_values) if confidence_values else None,
            "source_bounds": {
                "left": region["left"],
                "top": region["top"],
                "right": region["right"],
                "bottom": region["bottom"],
                "page_width": region["page_width"],
                "page_height": region["page_height"],
            },
            "order": int(heading.get("order", 0)),
        }
        replacements[str(heading["id"])] = box_section
        used.update(str(block.get("id", "")) for block in contained)

    output: list[dict[str, Any]] = []
    for block in blocks:
        block_id = str(block.get("id", ""))
        replacement = replacements.get(block_id)
        if replacement is not None:
            output.append(replacement)
        elif block_id not in used:
            output.append(block)
    return [{**block, "order": index} for index, block in enumerate(output)]



_MIN_QUOTE_SPAN_FRACTION = 0.55
_MAX_FLAT_EXCURSION = 3.0
_MIN_TAIL_EXCURSION = 8.0


def _stroke_extent(drawing: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Return the ``(left, top, right, bottom)`` bounds of a stroke's points."""
    xs: list[float] = []
    ys: list[float] = []
    for kind, *args in drawing.get("items", []):
        if kind not in {"l", "c"}:
            continue
        for point in args:
            xs.append(float(point.x))
            ys.append(float(point.y))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def detect_quote_regions(pdf_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Find quotation panels drawn as a top line plus a speech-bubble bottom.

    A quote is a wide, mostly horizontal bracket drawn with vector strokes: a
    flat line along the top of the text and, beneath the text, a line whose
    centre drops into a short downward V-shaped tail (the bubble pointer).
    Both strokes span most of the page width and share the same horizontal
    extent, so the region they enclose (top line down to the deepest part of
    the tail, which also catches the speaker attribution) is one quote.
    """
    try:
        import fitz
    except ImportError:
        return [], ["PyMuPDF unavailable; quote detection was skipped."]

    regions: list[dict[str, Any]] = []
    try:
        pdf = fitz.open(pdf_path)
        for page_index, page in enumerate(pdf):
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            flat_lines: list[dict[str, Any]] = []
            tailed_lines: list[dict[str, Any]] = []
            for drawing in page.get_drawings():
                if drawing.get("type") not in {"s", "fs"}:
                    continue
                if drawing.get("color") is None:
                    continue
                extent = _stroke_extent(drawing)
                if extent is None:
                    continue
                left, top, right, bottom = extent
                span = right - left
                excursion = bottom - top
                if span < page_width * _MIN_QUOTE_SPAN_FRACTION:
                    continue
                if excursion <= _MAX_FLAT_EXCURSION:
                    flat_lines.append(
                        {"left": left, "right": right, "top": top, "bottom": bottom}
                    )
                elif excursion >= _MIN_TAIL_EXCURSION:
                    tailed_lines.append(
                        {"left": left, "right": right, "top": top, "bottom": bottom}
                    )
            for top_line in flat_lines:
                for bottom_line in tailed_lines:
                    if bottom_line["top"] <= top_line["bottom"] + 4:
                        continue
                    overlap_left = max(top_line["left"], bottom_line["left"])
                    overlap_right = min(top_line["right"], bottom_line["right"])
                    if overlap_right - overlap_left < page_width * 0.4:
                        continue
                    regions.append(
                        {
                            "page": page_index + 1,
                            "left": overlap_left,
                            "top": top_line["top"],
                            "right": overlap_right,
                            "bottom": bottom_line["bottom"],
                            "page_width": page_width,
                            "page_height": page_height,
                        }
                    )
    except Exception as exc:
        return [], [f"Quote detection failed ({exc})."]
    return regions, []


def group_quote_blocks(
    blocks: list[dict[str, Any]],
    regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse each quote panel into one ``quote`` semantic block."""
    used: set[str] = set()
    replacements: dict[str, dict[str, Any]] = {}
    for region in regions:
        contained = [
            block
            for block in blocks
            if str(block.get("id", "")) not in used
            and block.get("label") not in {
                "title",
                "chapter_title",
                "box_section",
                "header",
                "footer",
                "document_index",
            }
            and _block_in_region(block, region)
        ]
        contained.sort(key=lambda block: int(block.get("order", 0)))
        if len(contained) < 1 or not any(
            str(block.get("text", "")).strip() for block in contained
        ):
            continue
        confidence_values = [
            float(block["confidence"])
            for block in contained
            if block.get("confidence") is not None
        ]
        quote = {
            "id": f"quote:{contained[0]['id']}",
            "label": "quote",
            "text": "\n\n".join(
                str(block.get("text", "")).strip()
                for block in contained
                if str(block.get("text", "")).strip()
            ),
            "quote_detected": True,
            "quote_blocks": contained,
            "page": int(region["page"]),
            "confidence": min(confidence_values) if confidence_values else None,
            "source_bounds": {
                "left": region["left"],
                "top": region["top"],
                "right": region["right"],
                "bottom": region["bottom"],
                "page_width": region["page_width"],
                "page_height": region["page_height"],
            },
            "order": int(contained[0].get("order", 0)),
        }
        replacements[str(contained[0]["id"])] = quote
        used.update(str(block.get("id", "")) for block in contained)

    output: list[dict[str, Any]] = []
    for block in blocks:
        block_id = str(block.get("id", ""))
        replacement = replacements.get(block_id)
        if replacement is not None:
            output.append(replacement)
        elif block_id not in used:
            output.append(block)
    return [{**block, "order": index} for index, block in enumerate(output)]
