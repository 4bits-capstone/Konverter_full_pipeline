"""A reviewer can set italic/bold on a style-capable block while editing it.

Detected styles live on the block as `styles` + `styles_text` and are only
honoured while the block text still equals `styles_text`, so a plain text
edit drops them. Saving ranges together with the text (`corrected_styles`)
re-anchors them to the new text.
"""

from __future__ import annotations

from app.service import WorkflowService
from app.text_styles import normalize_style_runs, styles_for_text


def _footnote(text: str = "See Smith v Jones (1990) 12 CLR 3.", **extra):
    block = {"id": "b1", "label": "footnote", "text": text, **extra}
    item = {
        "id": "r1",
        "block_id": "b1",
        "type": "footnote",
        "label": "Footnote",
        "extracted_text": text,
        "corrected_text": None,
    }
    return item, block


def _run(start, end, italic=False, bold=False):
    return {"start": start, "end": end, "italic": italic, "bold": bold}


def test_saved_styles_are_stored_against_the_new_text():
    item, block = _footnote()
    text = "See Smith v Jones (1990) 12 CLR 3 (edited)."
    WorkflowService._apply_review_item_changes(
        [item],
        [block],
        "r1",
        {"corrected_text": text, "corrected_styles": [_run(4, 17, italic=True)]},
    )
    assert block["text"] == text
    assert block["styles_text"] == text
    assert styles_for_text(block, text) == [_run(4, 17, italic=True)]
    assert text[4:17] == "Smith v Jones"


def test_text_edit_without_styles_drops_detected_styles():
    item, block = _footnote(
        styles=[_run(4, 17, italic=True)],
        styles_text="See Smith v Jones (1990) 12 CLR 3.",
    )
    WorkflowService._apply_review_item_changes(
        [item], [block], "r1", {"corrected_text": "Something else entirely."}
    )
    assert styles_for_text(block, block["text"]) == []


def test_empty_style_list_clears_existing_styles():
    item, block = _footnote(
        styles=[_run(4, 17, italic=True)],
        styles_text="See Smith v Jones (1990) 12 CLR 3.",
    )
    WorkflowService._apply_review_item_changes(
        [item],
        [block],
        "r1",
        {"corrected_text": "See Smith v Jones (1990) 12 CLR 3.", "corrected_styles": []},
    )
    assert "styles" not in block
    assert "styles_text" not in block


def test_ranges_are_relative_to_the_trimmed_text():
    item, block = _footnote()
    WorkflowService._apply_review_item_changes(
        [item],
        [block],
        "r1",
        {"corrected_text": "  Ibid 5.  ", "corrected_styles": [_run(0, 4, italic=True)]},
    )
    assert block["text"] == "Ibid 5."
    assert item["corrected_text"] == "Ibid 5."
    assert styles_for_text(block, "Ibid 5.") == [_run(0, 4, italic=True)]


def test_styles_are_stored_for_text_targets():
    item, block = _footnote()
    item["type"] = "text"
    block["label"] = "text"
    WorkflowService._apply_review_item_changes(
        [item],
        [block],
        "r1",
        {
            "type": "text",
            "corrected_text": "Plain.",
            "corrected_styles": [_run(0, 5, italic=True)],
        },
    )
    assert block["styles"] == [_run(0, 5, italic=True)]
    assert block["styles_text"] == "Plain."


def test_normalize_clamps_trims_overlaps_and_drops_unstyled():
    runs = [
        _run(5, 100, bold=True),
        _run(0, 8, italic=True),
        _run(2, 3),  # no style at all
        _run(9, 9, italic=True),  # empty
    ]
    assert normalize_style_runs(runs, 12) == [
        _run(0, 8, italic=True),
        _run(8, 12, bold=True),
    ]


class _StubStore:
    def __init__(self, blocks):
        self._blocks = blocks

    def read_artifact(self, document_id, name, default=None):
        assert name == "blocks.json"
        return self._blocks


def _service(blocks):
    service = WorkflowService.__new__(WorkflowService)
    service.store = _StubStore(blocks)
    return service


def test_served_style_capable_items_carry_styles_that_match_their_shown_text():
    text = "See Smith v Jones (1990) 12 CLR 3."
    item, block = _footnote(text, styles=[_run(4, 17, italic=True)], styles_text=text)
    other = {"id": "r2", "block_id": "b2", "type": "text", "extracted_text": "x"}
    served = _service([block]).with_item_styles("doc", [item, other])
    assert served[0]["styles"] == [_run(4, 17, italic=True)]
    assert served[1]["styles"] is None
    assert "styles" not in item  # never mutates what gets persisted


def test_served_text_items_carry_their_detected_styles():
    text = "Principles of Criminal Law."
    block = {
        "id": "b2",
        "label": "text",
        "text": text,
        "styles": [_run(0, 10, italic=True)],
        "styles_text": text,
    }
    item = {
        "id": "r2",
        "block_id": "b2",
        "type": "text",
        "label": "Text",
        "extracted_text": text,
        "corrected_text": None,
    }
    served = _service([block]).with_item_styles("doc", [item])
    assert served[0]["styles"] == [_run(0, 10, italic=True)]


def test_served_footnote_ignores_styles_for_a_stale_text():
    item, block = _footnote(
        styles=[_run(4, 17, italic=True)], styles_text="the text before an edit"
    )
    served = _service([block]).with_item_styles("doc", [item])
    assert served[0]["styles"] is None


def test_served_footnote_matches_despite_surrounding_whitespace():
    text = "Ibid 5."
    item, block = _footnote(f"{text}\n", styles=[_run(0, 4, italic=True)], styles_text=text)
    served = _service([block]).with_item_styles("doc", [item])
    assert served[0]["styles"] == [_run(0, 4, italic=True)]
