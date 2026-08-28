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



# Quote recognition uses PDF geometry plus typography/context, never paragraph
# numbers or report-specific phrases. All bounds use top-left PDF coordinates.
_SPEECH_CUE = re.compile(
    r"\b(?:said|say|says|stated?|states|told|noted?|notes|observed?|observes|"
    r"explained?|explains|reported?|reports|submitted?|submits|argued?|argues|"
    r"commented?|comments|wrote|writes|recalled?|recalls|described?|describes|referred|"
    r"emphasi[sz]ed?|according to|in (?:the )?words of)\b", re.I,
)
_NUMBER_OR_LIST = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]?\s|[•●▪–-]\s|\([a-z0-9]+\)\s)")


def _pdf_quote_lines(page: Any) -> list[dict[str, Any]]:
    lines = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(str(span.get("text", "")) for span in spans).strip()
            if not text or tuple(line.get("dir", (1, 0))) != (1, 0):
                continue
            x0, y0, x1, y1 = map(float, line["bbox"])
            weight = sum(len(span.get("text", "")) for span in spans) or 1
            italic = sum(len(span.get("text", "")) for span in spans if int(span.get("flags", 0)) & 2) / weight
            size = max((float(span.get("size", 0)) for span in spans), default=0)
            lines.append(dict(left=x0, top=y0, right=x1, bottom=y1, text=text, italic=italic, size=size, superscript=any(int(span.get("flags", 0)) & 1 for span in spans)))
    return sorted(lines, key=lambda line: (round(line["top"], 1), line["left"]))


def _quote_region(page: Any, page_number: int, lines: list[dict[str, Any]], kind: str, **bounds: float) -> dict[str, Any]:
    content = " ".join(line["text"] for line in lines)
    attribution = re.search(r"[—–]\s*([A-Z][\w .,’'&()-]{2,100})$", content)
    return {
        "attribution": attribution[1].strip() if attribution else "",
        "page": page_number, "page_width": float(page.rect.width),
        "page_height": float(page.rect.height), "kind": kind,
        "text": " ".join(line["text"] for line in lines),
        "left": min(line["left"] for line in lines),
        "top": min(line["top"] for line in lines),
        "right": max(line["right"] for line in lines),
        "bottom": max(line["bottom"] for line in lines), **bounds,
    }


def _quote_strokes(page: Any) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    flat, tailed = [], []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is None:
            continue
        # Some PDFs encode a horizontal rule as a thin filled rectangle.
        if rect.width >= page.rect.width * .45 and rect.height <= 3:
            if drawing.get("color") is not None or drawing.get("fill") is not None:
                flat.append(dict(left=float(rect.x0), right=float(rect.x1), top=float(rect.y0), bottom=float(rect.y1)))
            continue
        if drawing.get("type") not in {"s", "fs"} or drawing.get("color") is None:
            continue
        segments = []
        for item in drawing.get("items", []):
            if item[0] == "l":
                a, b = item[1:3]
                if abs(a.y-b.y) <= 3 and abs(a.x-b.x) >= page.rect.width*.2:
                    segments.append(dict(left=min(a.x,b.x), right=max(a.x,b.x), top=min(a.y,b.y), bottom=max(a.y,b.y)))
        # Restrict a pointer to a shallow, wide stroke, excluding table frames.
        if rect.width >= page.rect.width*.45 and 8 <= rect.height <= 45 and segments:
            tailed.append(dict(left=float(rect.x0), right=float(rect.x1), top=float(rect.y0), bottom=float(rect.y1)))
        else:
            flat.extend(segment for segment in segments if segment["right"]-segment["left"] >= page.rect.width*.45)
    unique = {(round(r["left"], 1), round(r["top"], 1), round(r["right"], 1)): r for r in flat}
    return sorted(unique.values(), key=lambda r:r["top"]), tailed


def detect_quote_regions(pdf_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Find ruled, speech-bubble and attributed indented quotations.

    Rules alone are insufficient: straight panels must also contain mostly
    italic text or an explicit attribution. Indented prose requires a speech
    introduction (or an opening quote), so ordinary lists are left alone.
    """
    try:
        import fitz
    except ImportError:
        return [], ["PyMuPDF unavailable; quote detection was skipped."]
    regions: list[dict[str, Any]] = []
    try:
        with fitz.open(pdf_path) as pdf:
            previous_page_tail: list[dict[str, Any]] = []
            for page_index, page in enumerate(pdf):
                lines = _pdf_quote_lines(page)
                flat, tailed = _quote_strokes(page)
                page_regions = []
                for top in flat:
                    candidates = [
                        (bottom, is_tail) for bottom, is_tail in
                        [(r, False) for r in flat] + [(r, True) for r in tailed]
                        if 18 <= bottom["top"]-top["bottom"] <= min(320, page.rect.height*.4)
                        and abs(bottom["left"]-top["left"]) <= 14
                        and abs(bottom["right"]-top["right"]) <= 14
                    ]
                    # Only the nearest matching lower boundary may close a panel.
                    if not candidates:
                        continue
                    bottom, is_tail = min(candidates, key=lambda pair: pair[0]["top"])
                    contained = [line for line in lines
                        if top["left"]-3 <= line["left"] and line["right"] <= top["right"]+3
                        and top["bottom"]+1 <= line["top"] and line["bottom"] <= bottom["bottom"]+3]
                    content = " ".join(line["text"] for line in contained)
                    if len(content.split()) < 6 or any(_NUMBER_OR_LIST.match(line["text"]) for line in contained):
                        continue
                    italic = sum(len(line["text"])*line["italic"] for line in contained) / max(len(content), 1)
                    attributed = bool(re.search(r"[—–]\s*[A-Z][\w .,’'&()-]{2,100}$", content))
                    if not is_tail and italic < .6 and not attributed:
                        continue
                    attribution_line = ""
                    if is_tail:
                        # An attribution may sit just below the pointer, but never
                        # include the next numbered paragraph or a long body line.
                        for line in lines:
                            if bottom["top"] <= line["top"] <= bottom["bottom"]+12 and line not in contained and line["left"] > page.rect.width*.45 and len(line["text"].split()) <= 14 and not _NUMBER_OR_LIST.match(line["text"]):
                                contained.append(line)
                                attribution_line = line["text"]
                    region = _quote_region(page, page_index+1, contained, "speech-bubble" if is_tail else "ruled")
                    if attribution_line:
                        region["attribution"] = attribution_line
                    page_regions.append(region)

                def has_list_marker(line: dict[str, Any]) -> bool:
                    return any(marker["left"] < line["left"] and abs(marker["top"]-line["top"]) <= 4
                        and re.fullmatch(r"(?:[•●▪–-]|\d+(?:\.\d+)*[.)]?|\([a-z0-9]+\))", marker["text"])
                        for marker in lines)

                prose = [line for line in lines if not re.fullmatch(r"[\d.()•●▪–-]+", line["text"]) and line["size"] >= 8 and line["top"] > page.rect.height*.06 and line["bottom"] < page.rect.height*.92]
                for index, line in enumerate(prose):
                    if (not index and not previous_page_tail) or _NUMBER_OR_LIST.match(line["text"]) or has_list_marker(line):
                        continue
                    prior = prose[max(0,index-4):index] if index else previous_page_tail
                    previous = prior[-1]
                    context = " ".join(l["text"] for l in prior)
                    introduction = previous["text"].rstrip().endswith(":")
                    if not introduction:
                        continue
                    indent = line["left"]-previous["left"]
                    if not (12 <= indent <= page.rect.width*.18 and (not index or 0 <= line["top"]-previous["bottom"] <= 32)):
                        continue
                    quoted = []
                    for following in prose[index:]:
                        if has_list_marker(following) or abs(following["left"]-line["left"]) > 5 or _NUMBER_OR_LIST.match(following["text"]) or following["size"] > previous["size"]*1.1:
                            break
                        if quoted and following["top"]-quoted[-1]["bottom"] > 20:
                            break
                        quoted.append(following)
                    typographic_quote = bool(quoted and len(quoted) >= 2 and quoted[0]["size"] < previous["size"]-.2 and quoted[-1]["superscript"])
                    if (_SPEECH_CUE.search(context) or typographic_quote) and len(" ".join(l["text"] for l in quoted).split()) >= 6:
                        region = _quote_region(page, page_index+1, quoted, "indented")
                        if not any(_block_in_region({"page": page_index+1,"source_bounds":region}, r) for r in page_regions):
                            page_regions.append(region)
                previous_page_tail = [line for line in prose if line["size"] >= 9][-4:]
                regions.extend(sorted(page_regions, key=lambda r:(r["top"],r["left"])))
    except Exception as exc:
        return [], [f"Quote detection failed ({exc})."]
    return regions, []


def group_quote_blocks(blocks: list[dict[str, Any]], regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group only text contained by a quote, preserving source order/evidence."""
    output = list(blocks)
    excluded = {"title", "chapter_title", "box_section", "header", "footer", "document_index", "footnote", "table", "picture", "quote", "list", "list_item"}
    for region in regions:
        # Docling can merge the introduction, quote and next paragraph. Split
        # only an exact whitespace-normalized match; never replace its text with
        # a second OCR reading. Keep every surrounding character and its order.
        region_text = re.sub(r"\s+", "", str(region.get("text", ""))).casefold()
        split_output = []
        for block in output:
            raw = str(block.get("text", ""))
            bounds = block.get("source_bounds")
            if region_text and bounds and block.get("label") in {"text", "paragraph", "unspecified"} and int(block.get("page", 1)) == int(region["page"]) and bounds["top"] < region["bottom"] and bounds["bottom"] > region["top"]:
                folded = [(i, char) for i, original in enumerate(raw) if not original.isspace() for char in original.casefold()]
                positions = [i for i, _ in folded]
                compact = "".join(char for _, char in folded)
                start = compact.find(region_text)
                if start >= 0 and len(compact) > len(region_text):
                    begin, end = positions[start], positions[start+len(region_text)-1]+1
                    if raw[:begin].strip():
                        split_output.append({**block, "text": raw[:begin].strip(), "source_bounds": {**bounds, "bottom": min(bounds["bottom"],region["top"])}})
                    split_output.append({**block, "id": f"{block['id']}:quote", "text": raw[begin:end].strip(), "source_bounds": {key:region[key] for key in ("left","top","right","bottom","page_width","page_height")}})
                    if raw[end:].strip():
                        split_output.append({**block, "id": f"{block['id']}:after-quote", "text": raw[end:].strip(), "source_bounds": {**bounds, "top": max(bounds["top"],region["bottom"])}})
                    continue
            split_output.append(block)
        output = split_output
        selected = []
        for index, block in enumerate(output):
            label = str(block.get("label", ""))
            if label in excluded or label.startswith("section_header") or block.get("toc_derived") or not _block_in_region(block, region):
                continue
            bounds = block["source_bounds"]
            intersection = max(0, min(bounds["bottom"],region["bottom"])-max(bounds["top"],region["top"]))
            # PDF and Docling glyph bounds differ slightly. Reject combined
            # body/quote blocks rather than silently swallowing surrounding prose.
            if intersection / max(bounds["bottom"]-bounds["top"], 1) < .7:
                continue
            selected.append(index)
        if not selected:
            continue
        contained = [output[i] for i in selected]
        text = "\n\n".join(str(b.get("text", "")).strip() for b in contained if str(b.get("text", "")).strip())
        if not text:
            continue
        scores = [float(b["confidence"]) for b in contained if b.get("confidence") is not None]
        quote = {
            "id": f"quote:{contained[0]['id']}", "label": "quote", "text": text,
            "quote_detected": True, "quote_blocks": contained,
            "quote_kind": region.get("kind", "ruled"), "quote_attribution": region.get("attribution", ""), "page": int(region["page"]),
            "confidence": min(scores) if scores else None,
            "source_bounds": {key:region[key] for key in ("left","top","right","bottom","page_width","page_height")},
            "order": contained[0].get("order", 0),
        }
        selected_set = set(selected)
        output = [quote if i == selected[0] else b for i,b in enumerate(output) if i == selected[0] or i not in selected_set]
    return [{**block, "order": index} for index, block in enumerate(output)]
