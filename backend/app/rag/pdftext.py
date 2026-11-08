"""The PDF's own text layer, one string per page (pypdfium2 is already a dependency)."""
from __future__ import annotations

from pathlib import Path


def pdf_page_texts(path: Path) -> list[str]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    finally:
        pdf.close()
