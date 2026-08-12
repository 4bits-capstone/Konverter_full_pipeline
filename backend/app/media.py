from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import ImageDraw

try:
    from docling.utils.locks import pypdfium2_lock as pdfium_lock
except Exception:
    pdfium_lock = threading.Lock()


def pdf_page_count(source_path: Path) -> int:
    """Return the page count of a PDF, serialised with all pdfium use."""
    with pdfium_lock:
        document = pdfium.PdfDocument(str(source_path))
        try:
            return len(document)
        finally:
            document.close()


def _crop_to_bounds(
    image: Any,
    bounds: dict[str, Any],
    padding: int,
    *,
    highlight: bool = False,
) -> Any:
    page_width = float(bounds.get("page_width", 0))
    page_height = float(bounds.get("page_height", 0))
    if page_width <= 0 or page_height <= 0:
        return image
    scale_x = image.width / page_width
    scale_y = image.height / page_height
    left = max(0, round(float(bounds.get("left", 0)) * scale_x) - padding)
    top = max(0, round(float(bounds.get("top", 0)) * scale_y) - padding)
    right = min(
        image.width,
        round(float(bounds.get("right", page_width)) * scale_x) + padding,
    )
    bottom = min(
        image.height,
        round(float(bounds.get("bottom", page_height)) * scale_y) + padding,
    )
    if right > left and bottom > top:
        cropped = image.crop((left, top, right, bottom))
        if highlight:
            target_left = max(1, round(float(bounds.get("left", 0)) * scale_x) - left)
            target_top = max(1, round(float(bounds.get("top", 0)) * scale_y) - top)
            target_right = min(
                cropped.width - 2,
                round(float(bounds.get("right", page_width)) * scale_x) - left,
            )
            target_bottom = min(
                cropped.height - 2,
                round(float(bounds.get("bottom", page_height)) * scale_y) - top,
            )
            if target_right > target_left and target_bottom > target_top:
                draw = ImageDraw.Draw(cropped, "RGBA")
                draw.rectangle(
                    (target_left, target_top, target_right, target_bottom),
                    fill=(255, 193, 7, 42),
                    outline=(205, 96, 0, 255),
                    width=3,
                )
        return cropped
    return image


def _save_png(image: Any, destination: Path) -> None:
    temporary = destination.with_suffix(".tmp.png")
    image.save(temporary, format="PNG", optimize=True)
    os.replace(temporary, destination)


def render_pdf_region(
    source_path: Path,
    destination: Path,
    page_number: int,
    bounds: dict[str, Any] | None = None,
    *,
    dpi: int = 144,
    padding: int = 42,
    highlight: bool = False,
) -> None:
    """Render an original PDF page or one provenance-bounded region as PNG."""
    rendered = render_pdf_regions(
        source_path,
        [
            {
                "destination": destination,
                "page": page_number,
                "bounds": bounds,
                "dpi": dpi,
                "padding": padding,
                "highlight": highlight,
            }
        ],
    )
    if not rendered:
        raise RuntimeError(f"Page {page_number} could not be rendered")


def render_pdf_regions(source_path: Path, jobs: list[dict[str, Any]]) -> list[Path]:
    """Render many regions from one PDF while opening the document once.

    Each job: {"destination": Path, "page": int, "bounds": dict | None,
    "dpi": int, "padding": int}. Returns the destinations that rendered.
    Jobs that fail are skipped so one broken region cannot block the rest.
    """
    if not jobs:
        return []
    rendered: list[Path] = []
    with pdfium_lock:
        pdf = pdfium.PdfDocument(str(source_path))
        try:
            page_cache: dict[tuple[int, int], Any] = {}
            for job in jobs:
                destination = Path(job["destination"])
                try:
                    page_number = int(job["page"])
                    dpi = int(job.get("dpi", 144))
                    cache_key = (page_number, dpi)
                    image = page_cache.get(cache_key)
                    if image is None:
                        page = pdf[page_number - 1]
                        try:
                            bitmap = page.render(scale=dpi / 72)
                            image = bitmap.to_pil().convert("RGB")
                        finally:
                            page.close()
                        if len(page_cache) >= 4:
                            page_cache.clear()
                        page_cache[cache_key] = image
                    output = image
                    bounds = job.get("bounds")
                    if bounds:
                        output = _crop_to_bounds(
                            image,
                            bounds,
                            int(job.get("padding", 42)),
                            highlight=bool(job.get("highlight", False)),
                        )
                    _save_png(output, destination)
                    rendered.append(destination)
                except Exception:
                    destination.unlink(missing_ok=True)
                    continue
        finally:
            pdf.close()
    return rendered
