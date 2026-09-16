from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

from app.media import _crop_to_bounds, render_pdf_regions


def _write_pdf(path: Path, page_count: int = 3) -> None:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    with open(path, "wb") as handle:
        writer.write(handle)


def test_evidence_crops_are_distinct_and_highlight_the_requested_bounds():
    page = Image.new("RGB", (600, 800), "white")
    first_bounds = {
        "left": 50,
        "top": 100,
        "right": 250,
        "bottom": 160,
        "page_width": 600,
        "page_height": 800,
    }
    second_bounds = {
        "left": 300,
        "top": 500,
        "right": 540,
        "bottom": 620,
        "page_width": 600,
        "page_height": 800,
    }

    first = _crop_to_bounds(page, first_bounds, 20, highlight=True)
    second = _crop_to_bounds(page, second_bounds, 20, highlight=True)

    assert first.size == (240, 100)
    assert second.size == (280, 160)
    assert first.tobytes() != second.tobytes()
    # Padding shifts the requested region 20 pixels into each crop. The target
    # outline must therefore be present at that position rather than producing
    # an unmarked page screenshot.
    assert first.getpixel((20, 20)) == (205, 96, 0)
    assert second.getpixel((20, 20)) == (205, 96, 0)


def test_page_zero_is_rejected_instead_of_wrapping_to_the_last_page(tmp_path):
    """pdfium's page list is 0-indexed, so pdf[page_number - 1] with a
    page_number of 0 (missing/zero provenance from Docling) becomes
    pdf[-1] — Python's negative-index wraparound would silently render
    the *last* page of the document instead of failing the job the way
    an out-of-range page already does."""
    source = tmp_path / "source.pdf"
    _write_pdf(source, page_count=3)

    rendered = render_pdf_regions(
        source,
        [{"destination": tmp_path / "page-zero.png", "page": 0}],
    )

    assert rendered == []
    assert not (tmp_path / "page-zero.png").exists()


def test_valid_page_still_renders(tmp_path):
    source = tmp_path / "source.pdf"
    _write_pdf(source, page_count=3)
    destination = tmp_path / "page-two.png"

    rendered = render_pdf_regions(
        source, [{"destination": destination, "page": 2}]
    )

    assert rendered == [destination]
    assert destination.exists()
