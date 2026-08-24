from __future__ import annotations

from app.pipeline import _relabel_footnote_lists


def _list_block(entries: list[dict[str, object]], **overrides) -> dict[str, object]:
    block = {
        "id": "#/texts/5",
        "label": "list",
        "text": "\n".join(f"{entry['text']}" for entry in entries),
        "list_items": [entry["text"] for entry in entries],
        "list_entries": entries,
        "page": 3,
        "confidence": 0.7,
        "source_bounds": {"l": 0, "t": 0, "r": 1, "b": 1},
    }
    block.update(overrides)
    return block


def _entry(text: str, marker: str = "", enumerated: bool = False, level: int = 0):
    return {"text": text, "marker": marker, "enumerated": enumerated, "level": level}


def test_bare_numbered_footnote_apparatus_is_split_into_footnote_blocks():
    entries = [
        _entry("1 Submissions 12, 14 (2020)."),
        _entry("2 Above n 1, 45."),
        _entry("3 Bail Act 1977 (Vic) s 4(2)."),
    ]
    blocks = [_list_block(entries)]

    result = _relabel_footnote_lists(blocks)

    assert len(result) == 3
    assert all(block["label"] == "footnote" for block in result)
    assert result[0]["text"] == "1 Submissions 12, 14 (2020)."
    assert result[1]["text"] == "2 Above n 1, 45."
    assert result[2]["text"] == "3 Bail Act 1977 (Vic) s 4(2)."


def test_numbered_recommendations_without_footnote_vocabulary_are_untouched():
    entries = [
        _entry("1 The Department should review its intake process."),
        _entry("2 Funding should be extended for a further two years."),
    ]
    blocks = [_list_block(entries)]

    result = _relabel_footnote_lists(blocks)

    assert result == blocks


def test_single_entry_footnote_like_block_is_left_as_a_list():
    entries = [_entry("1 Bail Act 1977 (Vic) s 4(2), citing above n 3.")]
    blocks = [_list_block(entries)]

    result = _relabel_footnote_lists(blocks)

    assert result == blocks


def test_period_numbered_entries_are_not_reclassified_even_with_citation_vocabulary():
    entries = [
        _entry("1. See Bail Act 1977 (Vic) s 4(2)."),
        _entry("2. Ibid at [10]."),
    ]
    blocks = [_list_block(entries)]

    result = _relabel_footnote_lists(blocks)

    assert result == blocks


def test_mixed_vocabulary_below_majority_threshold_is_untouched():
    entries = [
        _entry("1 Ibid."),
        _entry("2 The committee heard evidence from three witnesses."),
        _entry("3 Funding was allocated in the prior budget cycle."),
    ]
    blocks = [_list_block(entries)]

    result = _relabel_footnote_lists(blocks)

    assert result == blocks


def test_non_list_blocks_pass_through_unchanged():
    blocks = [
        {"id": "#/texts/1", "label": "text", "text": "Hello", "page": 1, "confidence": 0.9},
        {"id": "#/texts/2", "label": "table", "text": "a | b", "page": 2, "confidence": 0.8},
    ]

    assert _relabel_footnote_lists(blocks) == blocks
