"""Italic/bold on body text (paragraphs, headings, quotes, captions) reaches
the exported HTML, and survives the footnote-link rewriting paragraphs get."""

from __future__ import annotations

from app.exporter import build_publication
from app.preview_html import _render_block, _render_inline_text
from app.service import WorkflowService


def _run(start, end, italic=False, bold=False):
    return {"start": start, "end": end, "italic": italic, "bold": bold}


def _publication(*blocks):
    return build_publication(
        [
            {"id": "t", "label": "title", "text": "Report", "order": 0},
            {"id": "s", "label": "section_header_1", "text": "Findings", "order": 1},
            *[{**block, "order": index + 2} for index, block in enumerate(blocks)],
        ],
        {"title": "Report", "pages": 1, "file_name": "report.pdf"},
    )


def test_paragraph_styles_render_as_em_and_strong():
    text = "See Smith v Jones for the rule."
    publication = _publication(
        {
            "id": "p",
            "label": "text",
            "text": text,
            "styles": [_run(4, 17, italic=True), _run(26, 30, bold=True)],
            "styles_text": text,
        }
    )
    paragraph = publication["sections"][0]["blocks"][0]
    assert _render_block(paragraph, None, {}) == (
        '<p class="docling-paragraph">See <em>Smith v Jones</em> for the '
        "<strong>rule</strong>.</p>"
    )


def test_numbered_paragraph_styles_are_rebased_past_the_number():
    text = "1.2 The court held that X applies."
    publication = _publication(
        {
            "id": "p",
            "label": "text",
            "text": text,
            "styles": [_run(4, 7, italic=True)],
            "styles_text": text,
        }
    )
    paragraph = publication["sections"][0]["blocks"][0]
    assert paragraph["number"] == "1.2"
    assert paragraph["text"] == "The court held that X applies."
    assert "<em>The</em> court" in _render_block(paragraph, None, {})


def test_stale_styles_are_ignored_after_the_text_changes():
    publication = _publication(
        {
            "id": "p",
            "label": "text",
            "text": "Edited text.",
            "styles": [_run(0, 4, italic=True)],
            "styles_text": "Original text.",
        }
    )
    assert "styles" not in publication["sections"][0]["blocks"][0]


def test_heading_and_caption_styles_render():
    publication = _publication(
        {
            "id": "h",
            "label": "section_header_2",
            "text": "The rule in Smith v Jones",
            "styles": [_run(12, 25, italic=True)],
            "styles_text": "The rule in Smith v Jones",
        },
        {
            "id": "c",
            "label": "caption",
            "text": "Figure 1 Flow",
            "styles": [_run(0, 8, bold=True)],
            "styles_text": "Figure 1 Flow",
        },
    )
    heading, caption = publication["sections"][0]["blocks"][:2]
    assert "<em>Smith v Jones</em></h2>" in _render_block(heading, None, {})
    assert "<strong>Figure 1</strong> Flow" in _render_block(caption, None, {})


def test_quote_styles_follow_their_paragraph():
    text = "First part.\n\nSecond part."
    block = {"type": "quote", "text": text, "styles": [_run(13, 19, italic=True)]}
    rendered = _render_block(block, None, {})
    assert "<p class=\"docling-paragraph\">First part.</p>" in rendered
    assert "<em>Second</em> part." in rendered


def test_styles_survive_footnote_reference_rewriting():
    # "held 3 3" is Docling's doubled reference; the second copy is dropped
    # and the surviving number becomes a link, with the italics intact.
    text = "The case Smith v Jones held 3 3 that it applies."
    rendered = _render_inline_text(
        text, {"3": "footnote-3"}, [_run(9, 22, italic=True)]
    )
    assert "<em>Smith v Jones</em>" in rendered
    assert 'aria-label="Footnote 3"' in rendered
    assert rendered.count(">3<") == 1


def test_unstyled_inline_text_is_unchanged():
    assert _render_inline_text("a < b", {}) == "a &lt; b"


def test_body_text_styles_are_saved_and_single_line_collapse_drops_them():
    item = {
        "id": "r1",
        "block_id": "b1",
        "type": "text",
        "label": "Text",
        "extracted_text": "Old",
        "corrected_text": None,
    }
    block = {"id": "b1", "label": "text", "text": "Old"}
    WorkflowService._apply_review_item_changes(
        [item],
        [block],
        "r1",
        {"corrected_text": "A case name here.", "corrected_styles": [_run(2, 11, italic=True)]},
    )
    assert block["styles"] == [_run(2, 11, italic=True)]
    assert block["styles_text"] == "A case name here."

    heading = {**item, "type": "section_header_2"}
    hblock = {"id": "b1", "label": "section_header_2", "text": "Old"}
    WorkflowService._apply_review_item_changes(
        [heading],
        [hblock],
        "r1",
        {"corrected_text": "Two\nlines", "corrected_styles": [_run(0, 3, italic=True)]},
    )
    assert "styles" not in hblock
