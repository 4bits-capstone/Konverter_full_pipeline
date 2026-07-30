from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium


def render_pdf_region(
    source_path: Path,
    destination: Path,
    page_number: int,
    bounds: dict[str, Any] | None = None,
    *,
    dpi: int = 144,
    padding: int = 42,
) -> None:
    """Render an original PDF page or one provenance-bounded region as PNG."""
    pdf = pdfium.PdfDocument(str(source_path))
    page = None
    try:
        page = pdf[page_number - 1]
        bitmap = page.render(scale=dpi / 72)
        image = bitmap.to_pil().convert("RGB")
        if bounds:
            page_width = float(bounds.get("page_width", 0))
            page_height = float(bounds.get("page_height", 0))
            if page_width > 0 and page_height > 0:
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
                    image = image.crop((left, top, right, bottom))
        temporary = destination.with_suffix(".tmp.png")
        image.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, destination)
    finally:
        if page is not None:
            page.close()
        pdf.close()
