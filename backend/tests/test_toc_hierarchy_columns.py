"""apply_outline (toc_hierarchy.py) merges the printed-TOC outline's
restored/promoted headings back into the document's own content. A real
bug found live in "Review of the Bail Act": a front-matter page pairs
"Terms of Reference" (left column) with "Acknowledgements", a contributor
list (right column) -- the exported document read "Acknowledgements. To
review the provisions of the Bail Act 1977... Bail Advisory Committee
[promoted to a heading] Philip Green Inspector...", interleaving the two
independent columns by raw vertical position.

The original fix re-sorted every block by (page, top) unconditionally,
which is what caused the bug in the first place -- Docling already runs a
real reading-order model (docling_ibm_models' rule-based predictor) and
gets this right; blanket re-sorting by raw vertical position discarded
that. A geometric column-clustering patch on top of that sort was tried
next, but stayed fragile (a stray off-page bounding box on a real
Bibliography page defeated it, and it could never generalise past exactly
two columns).

The actual fix: never re-sort real content at all. apply_outline now
preserves each page's existing block order completely and only splices in
outline entries (headings Docling missed or mislabeled) at their
approximate position. These tests pin that behaviour directly against
apply_outline, not a helper function, since the ordering guarantee is what
matters -- not how any one page happens to get classified.
"""

from __future__ import annotations

from app.toc_hierarchy import TocEntry, TocHierarchyResolver, TocOutline

PAGE_WIDTH = 595.276


def _block(ref: str, text: str, left: float, top: float, page: int = 7) -> dict[str, object]:
    return {
        "id": ref,
        "label": "text",
        "text": text,
        "page": page,
        "confidence": 0.9,
        "source_bounds": {"left": left, "top": top, "page_width": PAGE_WIDTH},
    }


def _resolver(entries: list[TocEntry]) -> TocHierarchyResolver:
    """Build a resolver with just enough state for apply_outline, without
    the PDF/document dependencies __init__ needs for TOC discovery."""
    resolver = object.__new__(TocHierarchyResolver)
    resolver.outline = TocOutline(entries=entries, toc_pages={1})
    return resolver


def test_two_column_front_matter_page_keeps_its_existing_order_untouched():
    """Reproduces the real bug shape directly: a front-matter page with no
    outline entries targeting it at all must come out of apply_outline
    exactly as it went in -- the whole point of the fix is that ordinary
    content is never re-sorted."""
    blocks = [
        _block("#/texts/0", "Terms of Reference", 40, 100),
        _block("#/texts/1", "To review the provisions...", 40, 155),
        _block("#/texts/2", "the presumption of innocence", 40, 193),
        _block("#/texts/3", "Acknowledgements", 300, 100),
        _block("#/texts/4", "Bail Advisory Committee", 300, 155),
        _block("#/texts/5", "Philip Green Inspector", 300, 170),
    ]

    result = _resolver([]).apply_outline(blocks)

    assert [b["id"] for b in result] == [
        "#/texts/0",
        "#/texts/1",
        "#/texts/2",
        "#/texts/3",
        "#/texts/4",
        "#/texts/5",
    ]


def test_matched_outline_entry_is_spliced_in_near_its_original_position():
    """A matched entry (Docling saw the text but mislabeled it) is removed
    from its old spot and re-inserted as a proper heading -- it should
    land back among its original page-2 neighbours, not at the start or
    end of the whole document."""
    blocks = [
        _block("#/texts/0", "Introduction", 40, 100, page=2),
        _block("#/texts/1", "chapter one heading", 40, 150, page=2),
        _block("#/texts/2", "Body text after the heading.", 40, 200, page=2),
        _block("#/texts/9", "Unrelated page 5 content", 40, 100, page=5),
    ]
    entry = TocEntry(
        title="Chapter One",
        level=1,
        printed_page="1",
        toc_page=1,
        bbox=(0, 0, 0, 0),
        target_page=2,
        matched_ref="#/texts/1",
    )

    result = _resolver([entry]).apply_outline(blocks)
    ids = [b["id"] for b in result]

    assert ids == ["#/texts/0", "#/texts/1", "#/texts/2", "#/texts/9"]
    promoted = next(b for b in result if b["id"] == "#/texts/1")
    assert promoted["label"] == "section_header_1"
    assert promoted["text"] == "Chapter One"


def test_unmatched_outline_entry_starts_a_fresh_page_with_no_existing_content():
    """A heading Docling missed entirely, restored purely from the printed
    contents page, targets a page with no other extracted content -- it
    should still land there rather than being dropped or misplaced."""
    blocks = [_block("#/texts/0", "Page 2 content", 40, 100, page=2)]
    entry = TocEntry(
        title="Chapter Two",
        level=1,
        printed_page="3",
        toc_page=1,
        bbox=(0, 0, 0, 0),
        target_page=3,
        target_y=50.0,
    )

    result = _resolver([entry]).apply_outline(blocks)

    assert [b["id"] for b in result] == ["#/texts/0", "#/toc-outline/0"]
    restored = result[1]
    assert restored["page"] == 3
    assert restored["text"] == "Chapter Two"


def test_outline_entries_on_one_page_never_disturb_other_pages():
    """A restored heading on page 3 must not touch the existing,
    already-correct order of blocks on any other page."""
    blocks = [
        _block("#/texts/0", "Left column, page 7", 40, 100, page=7),
        _block("#/texts/1", "Right column, page 7", 300, 100, page=7),
        _block("#/texts/2", "Page 3 content", 40, 100, page=3),
    ]
    entry = TocEntry(
        title="Restored Heading",
        level=2,
        printed_page="3",
        toc_page=1,
        bbox=(0, 0, 0, 0),
        target_page=3,
        target_y=10.0,
    )

    result = _resolver([entry]).apply_outline(blocks)
    page7_ids = [b["id"] for b in result if b["page"] == 7]

    assert page7_ids == ["#/texts/0", "#/texts/1"]
