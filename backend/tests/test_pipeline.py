from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.pipeline import KonverterPipeline, _relabel_footnote_lists


def _settings(**overrides) -> Settings:
    values = dict(
        data_dir=Path("/tmp/konverter-test"),
        cors_origins=("http://localhost:5173",),
        do_ocr=False,
        do_table_structure=True,
        docling_device="cpu",
        worker_count=1,
        max_pages=2000,
        high_confidence_threshold=0.75,
        medium_confidence_threshold=0.60,
        baseline_seconds_per_page=2.8,
        baseline_startup_seconds=30.0,
        site_url="",
        site_name="",
        page_url_template="",
        public_api_url="",
        default_license_url="",
        default_copyright_holder="",
        description_max_chars=600,
        log_level="INFO",
        openai_api_key="",
        docling_mode="local",
        docling_endpoint_url="",
        runpod_api_key="",
        storage_bucket="konverter-docs",
        signed_url_ttl=3600,
        supabase_url="",
        supabase_service_key="",
    )
    values.update(overrides)
    return Settings(**values)


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


def test_footnote_review_items_are_pre_accepted_but_other_types_stay_pending():
    blocks = [
        {
            "id": "#/texts/1",
            "label": "footnote",
            "text": "1 Ibid.",
            "page": 41,
            "confidence": 0.6,
        },
        {
            "id": "#/texts/2",
            "label": "text",
            "text": "Ordinary paragraph flagged for the same reason.",
            "page": 41,
            "confidence": 0.6,
        },
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks)

    assert {item["type"]: item["status"] for item in items} == {
        "footnote": "accepted",
        "text": "pending",
    }
