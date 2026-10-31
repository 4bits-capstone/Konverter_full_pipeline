from __future__ import annotations

import pymupdf

from app.preview_html import _render_footnotes_list
from app.text_styles import extract_style_ranges, render_styled, styles_for_text

BOUNDS = {"left": 40, "top": 90, "right": 560, "bottom": 130}


def _page(runs: list[tuple[str, str]]):
    """One-line PDF page; runs are (text, base-14 font) pairs."""
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=200)
    writer = pymupdf.TextWriter(page.rect)
    x = 50.0
    for text, fontname in runs:
        font = pymupdf.Font(fontname)
        writer.append((x, 110), text, font=font, fontsize=10)
        x += font.text_length(text, fontsize=10)
    writer.write_text(page)
    return page


def test_italic_title_is_recovered_as_exact_range():
    text = "2 Simon Bronitt, Principles of Criminal Law (4th ed, 2017) 194."
    page = _page(
        [
            ("2 Simon Bronitt, ", "helv"),
            ("Principles of Criminal Law", "heit"),
            (" (4th ed, 2017) 194.", "helv"),
        ]
    )
    ranges = extract_style_ranges(page, BOUNDS, text)
    assert ranges is not None and len(ranges) == 1
    run = ranges[0]
    assert text[run["start"] : run["end"]] == "Principles of Criminal Law"
    assert run["italic"] and not run["bold"]


def test_bold_and_italic_are_distinguished():
    text = "Alpha Beta Gamma"
    page = _page([("Alpha ", "hebo"), ("Beta ", "heit"), ("Gamma", "helv")])
    ranges = extract_style_ranges(page, BOUNDS, text)
    assert [(text[r["start"] : r["end"]], r["italic"], r["bold"]) for r in ranges] == [
        ("Alpha", False, True),
        ("Beta", True, False),
    ]


def test_unstyled_text_aligns_to_empty_ranges():
    page = _page([("Plain footnote text.", "helv")])
    assert extract_style_ranges(page, BOUNDS, "Plain footnote text.") == []


def test_fails_closed_when_text_does_not_match_pdf():
    page = _page([("Real ", "helv"), ("italic", "heit")])
    assert extract_style_ranges(page, BOUNDS, "Something else entirely") is None


def test_fails_closed_when_region_is_empty():
    page = _page([("Real text", "helv")])
    far = {"left": 40, "top": 10, "right": 560, "bottom": 30}
    assert extract_style_ranges(page, far, "Real text") is None


def test_styles_ignored_once_text_changes():
    block = {
        "text": "edited",
        "styles": [{"start": 0, "end": 3, "italic": True, "bold": False}],
        "styles_text": "original",
    }
    assert styles_for_text(block, "edited") == []
    assert styles_for_text(block, "original") != []


def test_render_styled_escapes_and_wraps():
    html_out = render_styled(
        "A <b> Case",
        [{"start": 2, "end": 5, "italic": True, "bold": False}],
    )
    assert html_out == "A <em>&lt;b&gt;</em> Case"


def test_footnote_list_applies_styles_after_number_is_stripped():
    text = "7 See Mabo v Queensland (1992)."
    start = text.index("Mabo v Queensland")
    notes = [
        {"id": "footnote-1", "text": "6 First.", "page": 1},
        {
            "id": "footnote-2",
            "text": text,
            "page": 1,
            "styles": [
                {"start": start, "end": start + len("Mabo v Queensland"), "italic": True, "bold": False}
            ],
        },
    ]
    out = _render_footnotes_list(notes)
    assert 'value="7">See <em>Mabo v Queensland</em> (1992).</li>' in out


def test_page_search_recovers_citation_when_bounds_cover_only_the_number():
    text = "9 Waller v Hargraves Commercial Pty Ltd (2001) 12 pages long."
    page = _page(
        [
            ("9 ", "helv"),
            ("Waller v Hargraves Commercial", "heit"),
            (" Pty Ltd (2001) 12 pages long.", "helv"),
        ]
    )
    number_only = {"left": 45, "top": 98, "right": 58, "bottom": 114}
    ranges = extract_style_ranges(page, number_only, text)
    assert ranges is not None and len(ranges) == 1
    assert text[ranges[0]["start"] : ranges[0]["end"]] == "Waller v Hargraves Commercial"


def test_page_search_refuses_ambiguous_text():
    text = "3 Repeated citation text that appears twice here."
    page = _page([("3 Repeated citation text that appears twice here.", "heit")])
    # Same line again lower on the page: the text is no longer unique.
    page.insert_text((50, 150), "3 Repeated citation text that appears twice here.", fontsize=10)
    number_only = {"left": 45, "top": 98, "right": 58, "bottom": 114}
    assert extract_style_ranges(page, number_only, text) is None
