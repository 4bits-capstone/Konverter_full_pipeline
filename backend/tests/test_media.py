from PIL import Image

from app.media import _crop_to_bounds


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
