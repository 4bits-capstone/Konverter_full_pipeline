"""Structure-label conversions (table/list/box_section/footnote/... in the
review UI) have repeatedly leaked a source block's raw, unstripped marker
characters ("• 114 Ibid 98.") into the converted output — five separate
instances of the same underlying mistake were found in one session,
because nothing exercised these paths. These tests pin the invariant that
should have caught all five: converting *from* a block whose clean
representation (list_entries, or a box_section's children) differs from
its raw text must never leak that raw text into *any* target type.
"""

from __future__ import annotations

from app.service import WorkflowService

BULLET = "•"  # the literal marker character these bugs leaked


def _list_block(**overrides):
    block = {
        "id": "b1",
        "label": "list",
        "text": f"{BULLET} 114 Ibid 98.\n{BULLET} 115 Tim Holding, Minister.",
        "list_items": ["114 Ibid 98.", "115 Tim Holding, Minister."],
        "list_entries": [
            {"text": "114 Ibid 98.", "marker": "", "enumerated": False, "level": 0},
            {
                "text": "115 Tim Holding, Minister.",
                "marker": "",
                "enumerated": False,
                "level": 0,
            },
        ],
    }
    block.update(overrides)
    return block


def _box_section_block(**overrides):
    block = {
        "id": "b1",
        "label": "box_section",
        "text": f"{BULLET} 2 The Act should define 'tree' to mean any perennial plant.",
        "box_section_title": "Recommendation",
        "box_section_kind": "recommendation",
        "box_section_blocks": [
            {
                "label": "text",
                "text": f"{BULLET} 2 The Act should define 'tree' to mean any perennial plant.",
            }
        ],
    }
    block.update(overrides)
    return block


def _apply(block: dict, target_type: str) -> dict:
    item = {"id": "r1", "block_id": block["id"], "type": block["label"], "label": "X"}
    WorkflowService._apply_review_item_changes([item], [block], "r1", {"type": target_type})
    return block


def test_list_to_footnote_strips_bullet_and_keeps_number_space_shape():
    block = _apply(_list_block(), "footnote")
    assert BULLET not in block["text"]
    assert block["text"] == "114 Ibid 98.\n115 Tim Holding, Minister."


def test_list_to_table_strips_bullet_from_cells():
    block = _apply(_list_block(), "table")
    assert BULLET not in block["text"]
    cells = [cell for row in block["table_data"]["rows"] for cell in row]
    cells += block["table_data"]["headers"]
    assert not any(BULLET in cell for cell in cells)


def test_list_to_quote_strips_bullet():
    block = _apply(_list_block(), "quote")
    assert BULLET not in block["text"]


def test_list_to_box_section_keeps_all_content_and_strips_bullet():
    block = _apply(_list_block(), "box_section")
    assert BULLET not in block["text"]
    # Regression guard: converting to box_section from a non-box_section
    # source must synthesise a child from the *original* block rather than
    # produce an empty box (block.get("box_section_blocks") starting empty).
    assert "114 Ibid 98." in block["text"]
    assert "115 Tim Holding, Minister." in block["text"]


def test_box_section_to_footnote_strips_bullet_from_child_text():
    block = _apply(_box_section_block(), "footnote")
    assert BULLET not in block["text"]
    assert block["text"] == "2 The Act should define 'tree' to mean any perennial plant."


def test_explicit_correction_is_never_overridden_by_source_cleaning():
    """An explicit edit is the reviewer's own intent — cleaning must never
    kick in once corrected_text/corrected_table is actually provided."""
    block = _apply_with_text(_list_block(), "footnote", f"{BULLET} kept verbatim")
    assert block["text"] == f"{BULLET} kept verbatim"


def _apply_with_text(block: dict, target_type: str, corrected_text: str) -> dict:
    item = {"id": "r1", "block_id": block["id"], "type": block["label"], "label": "X"}
    WorkflowService._apply_review_item_changes(
        [item], [block], "r1", {"type": target_type, "corrected_text": corrected_text}
    )
    return block


def test_numbered_text_converted_to_list_keeps_its_markers():
    """A follow-up review pass on the marker-stripping fix above introduced
    a regression: converting a block whose text merely *looks* like a
    numbered list ("1. First point") into an actual "list" type ran it
    through the same marker-stripping meant for already-list sources,
    deleting the "1."/"2." before _list_entries ever got a chance to
    recognise them as real markers — not just losing the marker
    classification, losing the digits themselves."""
    block = {
        "id": "b1",
        "label": "footnote",
        "text": "1. First point\n2. Second point",
    }
    item = {"id": "r1", "block_id": "b1", "type": "footnote", "label": "X"}
    WorkflowService._apply_review_item_changes([item], [block], "r1", {"type": "list"})
    assert block["text"] == "1. First point\n2. Second point"
    entries = block["list_entries"]
    assert [e["marker"] for e in entries] == ["1.", "2."]
    assert [e["enumerated"] for e in entries] == [True, True]


def test_any_reviewer_action_supersedes_the_pipelines_own_system_acceptance():
    """A footnote starts "accepted" by the pipeline itself, before any
    reviewer has opened the queue — Docling cannot preserve italics on PDF
    text (verified directly against this project's own Docling install),
    so an auto-accepted citation with an italicised case name may have
    already silently lost that styling unseen by anyone. The moment a
    reviewer actually acts on the item — even just re-confirming it via
    the "Confirm" button, sending back the same "accepted" status — that
    system-only claim must be superseded."""
    block = {"id": "b1", "label": "footnote", "text": "1 Smith v Jones (2020) 1 VR 100."}
    item = {
        "id": "r1",
        "block_id": "b1",
        "type": "footnote",
        "label": "Footnote",
        "status": "accepted",
        "reviewed_by": "system",
    }
    WorkflowService._apply_review_item_changes([item], [block], "r1", {"status": "accepted"})
    assert item["reviewed_by"] == "reviewer"


def test_box_section_correction_applies_regardless_of_child_count():
    """A box section with more than one contained block — any box with
    more than one sentence, the common case produced by
    visual_structure.py — silently discarded a reviewer's correction: the
    override only ever applied when there was exactly one child, so
    block["text"] was rebuilt from the stale, unedited children instead."""
    block = _box_section_block(
        box_section_blocks=[
            {"label": "text", "text": "First original sentence."},
            {"label": "text", "text": "Second original sentence."},
        ],
    )
    item = {"id": "r1", "block_id": "b1", "type": "box_section", "label": "X"}
    WorkflowService._apply_review_item_changes(
        [item], [block], "r1", {"corrected_text": "The reviewer's replacement text."}
    )
    assert block["text"] == "The reviewer's replacement text."


def test_table_to_footnote_keeps_one_citation_per_line():
    """Converting a table straight to "footnote" used to join every row
    with a single space, collapsing a whole table of separate citations
    (one per row) into one unbroken paragraph with no row boundary left to
    recover downstream — while table -> list -> footnote (going through
    the list branch, which always joins with "\\n") kept each citation on
    its own line. Both paths must produce the same per-row shape."""
    block = {
        "id": "b1",
        "label": "table",
        "text": "",
        "table_data": {
            "headers": ["Column 1", "Column 2"],
            "rows": [
                ["100", "Wrongs Act 1958 (Vic) s 48."],
                ["101", "Damage to property includes damage caused to anything."],
                ["102", "Wrongs Act 1958 (Vic) s 51(1)(a)."],
            ],
        },
    }
    item = {"id": "r1", "block_id": "b1", "type": "table", "label": "X"}
    WorkflowService._apply_review_item_changes([item], [block], "r1", {"type": "footnote"})
    lines = block["text"].split("\n")
    assert len(lines) == 3
    assert lines[0] == "100 Wrongs Act 1958 (Vic) s 48."
    assert lines[1] == "101 Damage to property includes damage caused to anything."
    assert lines[2] == "102 Wrongs Act 1958 (Vic) s 51(1)(a)."
