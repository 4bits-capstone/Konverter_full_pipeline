"""apply_outline's own final sort (toc_hierarchy.py) orders every block
purely by (page, top), which is what actually determines blocks.json's
final sequence — KonverterPipeline._column_aware_text_ranks runs earlier
in the pipeline and gets completely overridden by this sort. A real bug
found live in "Review of the Bail Act": a front-matter page pairs "Terms
of Reference" (left column) with "Acknowledgements", a contributor list
(right column) — the exported document read "Acknowledgements. To review
the provisions of the Bail Act 1977... Bail Advisory Committee [promoted
to a heading] Philip Green Inspector...", interleaving the two independent
columns by raw vertical position. These tests pin _column_offsets_by_page,
the function that makes apply_outline's sort column-aware.
"""

from __future__ import annotations

from app.toc_hierarchy import _column_offsets_by_page

PAGE_WIDTH = 595.276


def _block(ref: str, left: float, top: float, page: int = 7) -> dict[str, object]:
    return {
        "id": ref,
        "page": page,
        "source_bounds": {"left": left, "top": top, "page_width": PAGE_WIDTH},
    }


def test_two_column_front_matter_page_gets_a_column_offset():
    """Reproduces the real bug shape: a dense left column (few, multi-line
    blocks — a merged list group counts as one block) against a sparse,
    many-item right column (a name-and-title contributor list). The block
    count is lopsided (5 vs 50 in the real document) even though the split
    is completely genuine — this must not be mistaken for noise."""
    blocks = [
        _block("#/texts/0", 42.7, 102.0),  # Terms of Reference (left)
        _block("#/texts/1", 43.1, 156.0),  # left
        _block("#/groups/2", 43.7, 193.3),  # left, a merged bullet list
        _block("#/texts/3", 297.5, 102.0),  # Acknowledgements (right)
        _block("#/texts/4", 298.2, 156.5),  # right
    ]

    offsets = _column_offsets_by_page(blocks)

    assert offsets["#/texts/0"] == 0.0
    assert offsets["#/texts/1"] == 0.0
    assert offsets["#/groups/2"] == 0.0
    assert offsets["#/texts/3"] > offsets["#/texts/0"]
    assert offsets["#/texts/4"] > offsets["#/texts/0"]

    # Applying the offset the way apply_outline does (top += offset) must
    # sort every left-column block before every right-column block,
    # regardless of how the two columns interleave by raw vertical position.
    positioned = sorted(
        blocks,
        key=lambda block: (
            block["page"],
            block["source_bounds"]["top"] + offsets.get(block["id"], 0.0),
        ),
    )
    assert [block["id"] for block in positioned] == [
        "#/texts/0",
        "#/texts/1",
        "#/groups/2",
        "#/texts/3",
        "#/texts/4",
    ]


def test_single_column_page_gets_no_offsets():
    """The vast majority of pages are genuinely single-column — no offsets
    should be computed at all, so apply_outline's ordinary (page, top) sort
    stays completely untouched."""
    blocks = [
        _block("#/texts/0", 43.0, 100.0),
        _block("#/texts/1", 43.0, 150.0),
        _block("#/texts/2", 43.0, 200.0),
        _block("#/texts/3", 43.0, 250.0),
    ]

    assert _column_offsets_by_page(blocks) == {}


def test_single_stray_offcolumn_block_does_not_trigger_a_column_split():
    """A lone off-column element — a caption, a stray pull-quote — must
    never register as a second column on its own; only two clusters that
    each carry more than one block count as a genuine two-column layout."""
    blocks = [
        _block("#/texts/0", 43.0, 100.0),
        _block("#/texts/1", 43.0, 150.0),
        _block("#/texts/2", 43.0, 200.0),
        _block("#/texts/3", 43.0, 250.0),
        _block("#/texts/4", 320.0, 130.0),  # e.g. a lone figure caption
    ]

    assert _column_offsets_by_page(blocks) == {}


def test_already_column_ordered_page_still_gets_offsets_applied():
    """Unlike the pipeline.py equivalent, this must apply offsets even when
    the *input* block order already reads column-by-column — the (page,
    top) sort this feeds discards input order entirely and would otherwise
    re-interleave a column-clean input right back into vertical-position
    order on its own."""
    blocks = [
        _block("#/texts/0", 43.0, 100.0),
        _block("#/texts/1", 43.0, 150.0),
        _block("#/texts/2", 298.0, 100.0),
        _block("#/texts/3", 298.0, 150.0),
    ]

    offsets = _column_offsets_by_page(blocks)

    assert offsets["#/texts/2"] > offsets["#/texts/0"]
    assert offsets["#/texts/3"] > offsets["#/texts/0"]
