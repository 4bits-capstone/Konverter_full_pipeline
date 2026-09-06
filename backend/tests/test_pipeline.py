from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF, used only to build test fixture PDFs with real text

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
    # A footnote's "accepted" status is the pipeline's own decision, made
    # before any reviewer has seen the item — Docling cannot preserve
    # italics on PDF text (verified directly against this project's own
    # Docling install), so an auto-accepted citation with an italicised
    # case name may have already silently lost that styling. Tagging it
    # "system" keeps that distinct from a reviewer's own accept.
    assert {item["type"]: item.get("reviewed_by") for item in items} == {
        "footnote": "system",
        "text": None,
    }


def test_box_section_review_item_uses_childrens_clean_list_items():
    """A bulleted/numbered list absorbed into a callout panel by
    group_visual_callouts (visual_structure.py) becomes a box_section
    whose own "text" is just its children's raw text joined verbatim —
    markers included. The reviewer's *editable* starting text should be
    clean the same way a standalone list block's is, by preferring each
    child's own list_items when it has one."""
    blocks = [
        {
            "id": "box-section:1",
            "label": "box_section",
            "text": "• 114 Ibid 98.\n• 115 Tim Holding, Minister.",
            "box_section_title": "Recommendation",
            "box_section_blocks": [
                {
                    "id": "#/texts/2",
                    "label": "list",
                    "text": "• 114 Ibid 98.\n• 115 Tim Holding, Minister.",
                    "list_items": ["114 Ibid 98.", "115 Tim Holding, Minister."],
                }
            ],
            "page": 41,
            "confidence": 0.6,
        }
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks)

    assert len(items) == 1
    extracted = items[0]["extracted_text"]
    assert "•" not in extracted
    assert extracted == "114 Ibid 98.\n115 Tim Holding, Minister."


def _write_footnote_pdf(path: Path, footnote_text: str) -> dict:
    """A one-page PDF with a single line of real text at a known position,
    mimicking a footnote at the bottom of a page. Returns the source_bounds
    a Docling block for that text would carry (top-down, matching what
    pipeline.py's blocks actually use)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    x, y, fontsize = 72, 800, 9
    page.insert_text((x, y), footnote_text, fontsize=fontsize, fontname="helv")
    width = fitz.get_text_length(footnote_text, fontsize=fontsize, fontname="helv")
    doc.save(path)
    doc.close()
    # PyMuPDF's insert_text baseline sits a little above the glyphs'
    # descenders — pad the box generously so the real text is fully
    # enclosed, the same way real Docling provenance boxes are.
    return {
        "left": x - 2,
        "top": y - fontsize - 2,
        "right": x + width + 2,
        "bottom": y + 4,
        "page_width": 595,
        "page_height": 842,
    }


def test_footnote_matching_the_source_pdf_is_verified_and_pre_accepted(tmp_path):
    pdf_path = tmp_path / "source.pdf"
    footnote_text = "6 Lemmon v Webb [1895] AC 1."
    bounds = _write_footnote_pdf(pdf_path, footnote_text)
    blocks = [
        {
            "id": "#/texts/1",
            "label": "footnote",
            "text": footnote_text,
            "page": 1,
            "confidence": 0.6,
            "source_bounds": bounds,
        }
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks, pdf_path)

    assert len(items) == 1
    assert items[0]["status"] == "accepted"
    assert items[0]["reviewed_by"] == "system"


def test_footnote_disagreeing_with_the_source_pdf_is_not_pre_accepted(tmp_path):
    """Reproduces the real failure mode found in a 364-page VLRC report:
    Docling's own text for a footnote block can be truncated to a
    fragment of what's actually in that region of the PDF, with an
    unremarkable confidence score — cross-validating against an
    independent re-extraction of the same region is what catches it."""
    pdf_path = tmp_path / "source.pdf"
    real_text = "76 Joel Silver, Nuisance by Tree, permit the nuisance to be adopted."
    bounds = _write_footnote_pdf(pdf_path, real_text)
    blocks = [
        {
            "id": "#/texts/1",
            "label": "footnote",
            # Docling's own text for this block is a truncated fragment of
            # what's actually at these bounds in the PDF.
            "text": "76 permit the nuisance to be adopted.",
            "page": 1,
            "confidence": 0.6,
            "source_bounds": bounds,
        }
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks, pdf_path)

    assert len(items) == 1
    assert items[0]["status"] == "pending"
    assert items[0]["reviewed_by"] is None


def test_footnote_verification_is_skipped_without_a_pdf_path():
    """No pdf_path means there's no PDF to independently check against at
    all — that's "unverifiable", not "verified and wrong" — so it must
    fall back to the old trust-by-default behaviour rather than marking
    every footnote pending just because verification wasn't possible."""
    blocks = [
        {
            "id": "#/texts/1",
            "label": "footnote",
            "text": "1 Ibid.",
            "page": 1,
            "confidence": 0.6,
            "source_bounds": {
                "left": 72, "top": 800, "right": 200, "bottom": 812,
                "page_width": 595, "page_height": 842,
            },
        }
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks)

    assert items[0]["status"] == "accepted"
    assert items[0]["reviewed_by"] == "system"
