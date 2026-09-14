from __future__ import annotations

from app.footnote_numbering import resolve_footnote_number
from app.preview_html import _footnote_targets, _render_block, _render_footnotes_list


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


def test_a_stray_digit_glued_onto_a_footnotes_own_text_is_recovered_using_the_expected_sequence():
    """Real bug found live in "Birth Registration and Birth Certificates":
    footnote 16 and 17 sit on adjacent lines at the very bottom of a page,
    and Docling occasionally merges them into a single text item with a
    stray leftover digit glued onto the front of footnote 17's own text --
    "3 17 John Chesterman and Brian Galligan, Citizens without Rights...".
    Matched naively, "3" becomes footnote 17's displayed number, which
    breaks the whole section's increasing-number check and falls the
    entire section back to duplicate-number display -- not just this one
    entry. Once the caller knows 17 is the expected next number (16 came
    right before it), the alternate parse that actually equals 17 must
    win over the naive "3"."""
    assert resolve_footnote_number(
        "3 17 John Chesterman and Brian Galligan, Citizens without Rights "
        "(Cambridge University Press, 1997) 26.",
        expected=17,
    ) == ("17", "John Chesterman and Brian Galligan, Citizens without Rights (Cambridge University Press, 1997) 26.")


def test_a_real_citation_that_happens_to_open_with_two_numbers_is_left_alone():
    """A short-form case citation genuinely can open with two numbers --
    footnote 141 citing "410 US 113 (1973)." (a reporter volume and page)
    is completely legitimate text, not a merged pair of footnotes. The
    fix must only prefer the second number when it exactly equals the
    expected next footnote index; here the expected next index is 142,
    which "410" is nowhere near, so the naive (and correct) parse of 141
    must be kept."""
    assert resolve_footnote_number(
        "141 410 US 113 (1973).", expected=142
    ) == ("141", "410 US 113 (1973).")


def test_footnote_list_recovers_correct_numbering_across_the_stray_digit_bug():
    """End-to-end through _render_footnotes_list: a section with this bug
    must render every footnote's own real number instead of collapsing
    the whole section to position-counted duplicates."""
    notes = [
        {"id": "footnote-16", "text": "16 AIATSIS, above n 8."},
        {
            "id": "footnote-17",
            "text": "3 17 John Chesterman and Brian Galligan, Citizens without Rights, 26.",
        },
        {"id": "footnote-18", "text": "18 Ibid."},
    ]

    html_output = _render_footnotes_list(notes)

    assert 'value="16"' in html_output
    assert 'value="17"' in html_output
    assert 'value="18"' in html_output
    assert "3 17 John Chesterman" not in html_output


def test_footnote_targets_link_to_the_recovered_number_not_the_stray_digit():
    """_footnote_targets must key off the same recovered number _render_footnotes_list
    displays, or an in-body citation to "17" would silently fail to resolve while a
    citation to "3" (which was never printed anywhere in the body) claims the slot."""
    notes = [
        {"id": "footnote-16", "text": "16 AIATSIS, above n 8."},
        {
            "id": "footnote-17",
            "text": "3 17 John Chesterman and Brian Galligan, Citizens without Rights, 26.",
        },
    ]

    targets = _footnote_targets(notes)

    assert targets.get("17") == "footnote-17"
    assert "3" not in targets
