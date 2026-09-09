from __future__ import annotations

from app.preview_html import _render_block


def test_isolated_bare_number_paragraph_is_never_linked_to_an_unrelated_footnote():
    """Real bug found live in "Funeral and Burial Instructions": footnote
    17's own citation was run together with footnote 16's into a single
    Docling text item with no boundary between them, so pipeline.py's
    _repair_split_footnote_markers -- correctly refusing to guess where the
    merged text should split -- reunites 16 with that block and leaves 17
    as an honest, unrepaired bare-number paragraph. _footnote_targets'
    position-based fallback (used for footnotes with no parseable leading
    number of their own) can land on "17" purely by list position -- and
    did, live, pointing the floating "17" at a completely unrelated
    footnote's text. A genuine inline citation reference is always embedded
    inside a real sentence ("...ceremony.19"); a paragraph whose *entire*
    content is a bare number never is one, so it must render as plain text,
    never as a link, no matter what "17" happens to resolve to in this
    section's targets."""
    block = {"type": "paragraph", "text": "17"}
    footnote_targets = {"17": "footnote-20-2"}  # the real, wrong collision found live

    html_output = _render_block(block, None, footnote_targets)

    assert "<a href" not in html_output
    assert "17" in html_output


def test_a_genuine_inline_citation_reference_is_still_linked():
    """The fix above must not disable real inline footnote references --
    only a paragraph whose *entire* text is a bare number is ever suspect."""
    block = {
        "type": "paragraph",
        "text": "The woman chose not to disclose the information.22",
    }
    footnote_targets = {"22": "footnote-22"}

    html_output = _render_block(block, None, footnote_targets)

    assert '<a href="#footnote-22"' in html_output
    assert "Footnote 22" in html_output
