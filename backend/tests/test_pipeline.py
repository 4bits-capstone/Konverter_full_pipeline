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


def _write_mixed_font_size_pdf(path: Path, lines: list[tuple[str, int, int]]) -> list[dict]:
    """A one-page PDF with several lines of real text at given (text,
    fontsize, y) positions. Returns each line's source_bounds in the same
    top-down shape pipeline.py's blocks actually carry."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    all_bounds = []
    for text, fontsize, y in lines:
        page.insert_text((72, y), text, fontsize=fontsize, fontname="helv")
        width = fitz.get_text_length(text, fontsize=fontsize, fontname="helv")
        all_bounds.append({
            "left": 72 - 2,
            "top": y - fontsize - 2,
            "right": 72 + width + 2,
            "bottom": y + 4,
            "page_width": 595,
            "page_height": 842,
        })
    doc.save(path)
    doc.close()
    return all_bounds


def test_footnote_at_body_text_size_is_flagged_regardless_of_wording(tmp_path):
    """Reproduces the real bug's actual signal, isolated from wording: a
    footnote-labelled block rendered at this document's own body-text
    size (not its consistently smaller footnote size) must reach the
    review queue even with citation-shaped, unremarkable text and
    confidence above the auto-skip threshold — the font-size outlier
    check doesn't care what the text says, unlike the recommendation-
    language check."""
    pdf_path = tmp_path / "source.pdf"
    lines = [
        ("1 Ibid s 5.", 7, 700),
        ("2 Submission 4.", 7, 715),
        ("3 Ibid s 8.", 7, 730),
        ("4 Consultation 2.", 7, 745),
        # Same footnote label, ordinary citation wording, but rendered at
        # body-text size (12pt) instead of this document's 7pt footnotes.
        ("53 Consultation 9; submission 3.", 12, 400),
    ]
    bounds_list = _write_mixed_font_size_pdf(pdf_path, lines)
    blocks = [
        {
            "id": f"#/texts/{i}",
            "label": "footnote",
            "text": text,
            "page": 1,
            "confidence": 0.92,
            "source_bounds": bounds,
        }
        for i, ((text, _fontsize, _y), bounds) in enumerate(zip(lines, bounds_list))
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks, pdf_path)

    # The four genuine, consistently-sized footnotes stay above the
    # confidence threshold and correctly never become review items at
    # all — only the body-sized outlier is forced through.
    assert len(items) == 1
    assert items[0]["block_id"] == "#/texts/4"
    assert items[0]["status"] == "pending"
    assert items[0]["reviewed_by"] is None
    assert "body text" in items[0]["note"]


def test_second_legitimate_footnote_size_is_not_flagged_only_true_body_size_is(tmp_path):
    """Reproduces a real false-positive wave found in a 403-page report:
    it used two legitimate footnote sizes for different chapters (6.5pt
    and 8.6pt, both clearly smaller than its body text) — a baseline-
    only "bigger than the other footnotes" check flagged all 86 of the
    second, still-small cluster as if they were misclassified. Comparing
    against the document's own actual body-text size instead (not just
    "bigger than other footnotes") is what tells a second legitimate
    footnote convention apart from genuinely body-sized content."""
    pdf_path = tmp_path / "source.pdf"
    lines = [
        # Majority footnote cluster, 7pt.
        ("1 Ibid s 5.", 7, 700),
        ("2 Submission 4.", 7, 715),
        ("3 Ibid s 8.", 7, 730),
        ("4 Consultation 2.", 7, 745),
        ("5 Roundtable 1.", 7, 760),
        # A second, legitimate footnote convention elsewhere in the same
        # document — bigger than the 7pt majority, but still nowhere
        # near this document's own body-text size (13pt below).
        ("6 Submission 9.", 9, 550),
        ("7 Ibid s 12.", 9, 565),
        ("8 Consultation 5.", 9, 580),
        # Genuine body paragraphs, establishing this document's real
        # body-text size.
        ("This report examines pipeline readiness.", 13, 300),
        ("The Commission received several submissions.", 13, 320),
        ("Further consultation followed in due course.", 13, 340),
        # The actual bug: footnote-labelled, but rendered at body size.
        ("53 Consultation 9; submission 3.", 13, 100),
    ]
    bounds_list = _write_mixed_font_size_pdf(pdf_path, lines)
    footnote_line_indexes = {0, 1, 2, 3, 4, 5, 6, 7, 11}
    text_line_indexes = {8, 9, 10}
    blocks = [
        {
            "id": f"#/texts/{i}",
            "label": "footnote" if i in footnote_line_indexes else "text",
            "text": text,
            "page": 1,
            "confidence": 0.92,
            "source_bounds": bounds,
        }
        for i, ((text, _fontsize, _y), bounds) in enumerate(zip(lines, bounds_list))
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks, pdf_path)

    # Only the true body-sized outlier is forced through — the second,
    # still-small 9pt footnote cluster must not be flagged just for being
    # bigger than the 7pt majority.
    assert len(items) == 1
    assert items[0]["block_id"] == "#/texts/11"
    assert "body text" in items[0]["note"]


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


def test_high_confidence_footnote_with_recommendation_language_is_still_flagged():
    """Reproduces a real bug found in a 364-page VLRC report: three of the
    report's own numbered recommendations ("53 The Act should state that
    purchasers should be notified...") were labelled "footnote" instead
    of "list", at confidence 0.92 — comfortably above the high-confidence
    threshold that normally skips creating a review item at all. The text
    itself was character-for-character correct (so footnote text
    cross-validation alone wouldn't catch it either) — only the label was
    wrong, and nothing else in the pipeline questions a label once
    Docling is confident about it. This must still reach the review
    queue, marked pending, regardless of that confidence."""
    blocks = [
        {
            "id": "#/groups/1/footnote-0",
            "label": "footnote",
            "text": (
                "53 The Act should state that purchasers should be notified of any "
                "legal action commenced or underway at the time of the sale."
            ),
            "page": 304,
            "confidence": 0.92,
        }
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks)

    assert len(items) == 1
    assert items[0]["status"] == "pending"
    assert items[0]["reviewed_by"] is None
    assert items[0]["band"] == "high"
    assert "recommendation" in items[0]["note"].lower()


def test_genuine_high_confidence_footnote_citation_is_not_flagged():
    """A real citation that happens to use "should" while reporting what a
    submission argued (not the report's own recommendation) must not be
    swept up by the same check — citation vocabulary is what tells the
    two apart."""
    blocks = [
        {
            "id": "#/texts/1",
            "label": "footnote",
            "text": "156 Submissions 8, 11, 13. Victoria Legal Aid thought all headings in the Act should be amended.",
            "page": 115,
            "confidence": 0.92,
        }
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks)

    assert len(items) == 0


def test_footnote_describing_the_terms_of_reference_is_not_flagged():
    """A real false positive found in a genuine 192-page report: a
    footnote explaining what the terms of reference asked the Commission
    to examine ("...examine whether a certification requirement should be
    introduced...") tripped the recommendation-language check just from
    containing "should be introduced" — despite being a description of a
    question under consideration, not the report's own directive. The
    footnote's own confidence (0.84) already put it below the
    auto-skip threshold, so this wasn't hiding it from review — it was
    mislabelling *why* it needed review, which would have sent a
    reviewer down the wrong path (checking whether it should be a list,
    when it was correctly a footnote all along)."""
    blocks = [
        {
            "id": "#/texts/1",
            "label": "footnote",
            "text": (
                "The terms of reference direct the Commission to examine "
                "whether a certification requirement should be introduced "
                "in respect of class actions. The Commission considers "
                "there is no need to investigate the introduction of "
                "certification in these proceedings."
            ),
            "page": 100,
            # Below this test's own high_confidence_threshold (0.75), so
            # it becomes a review item through the ordinary path either
            # way — what's under test is which *note* it gets, not
            # whether it reaches the queue at all.
            "confidence": 0.6,
        }
    ]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks)

    assert len(items) == 1
    assert "recommendation" not in items[0]["note"].lower()
    assert "body text" not in items[0]["note"]


def test_decimal_paragraph_numbers_survive_into_extracted_text():
    """VLRC-style numbered paragraphs ("2.39", "7.2") are the report's own
    numbering system, not a stray list marker — the exporter specifically
    detects and preserves this exact marker shape
    (exporter._list_publication_blocks). The reviewer's "extracted result"
    should show the same number that ends up in the published document,
    or a reviewer has no way to notice it went missing until after
    delivery. Found live: 13,205 numbered paragraphs across 12 real VLRC
    documents were showing with the leading "2.39" silently stripped."""
    entries = [
        _entry(
            "People who have suffered significant injury may use "
            "assistance animals.",
            marker="2.39",
            enumerated=True,
        ),
        _entry(
            "The Transport Accident Commission (TAC) has been running a "
            "pilot program.",
            marker="2.40",
            enumerated=True,
        ),
    ]
    blocks = [_list_block(entries)]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks)

    assert len(items) == 1
    extracted = items[0]["extracted_text"]
    assert extracted.startswith("2.39 People who have suffered")
    assert "2.40 The Transport Accident Commission" in extracted


def test_ordinary_bullet_markers_are_still_stripped_from_extracted_text():
    """The decimal-paragraph-number carve-out above must not resurrect the
    original stray-marker bug for genuine bullets/footnote-style markers —
    those still shouldn't leak into the reviewer's editable text."""
    entries = [
        _entry("Ibid 98.", marker="114", enumerated=True),
        _entry("Tim Holding, Minister.", marker="115", enumerated=True),
    ]
    blocks = [_list_block(entries)]

    pipeline = KonverterPipeline(_settings())
    items = pipeline._build_review_items(blocks)

    assert len(items) == 1
    extracted = items[0]["extracted_text"]
    assert extracted == "Ibid 98.\nTim Holding, Minister."


def _text_item(
    ref: str, text: str, left: float, top: float, bottom: float, page: int = 1
) -> dict[str, object]:
    return {
        "self_ref": ref,
        "label": "text",
        "text": text,
        "prov": [
            {
                "page_no": page,
                "bbox": {
                    "l": left,
                    "t": top,
                    "r": left + 200,
                    "b": bottom,
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
    }


def test_two_column_front_matter_page_is_read_column_by_column_not_row_by_row():
    """Reproduces a real VLRC bug pattern found live in "Review of the Bail
    Act": a front-matter page pairs "Terms of Reference" (left column) with
    "Acknowledgements", a contributor list (right column). Docling emits
    both columns' text items in raw top-to-bottom document order, which
    interleaves the two independent columns into one incoherent reading
    sequence — the exported document ends up reading "Acknowledgements. To
    review the provisions of the Bail Act 1977... Bail Advisory Committee
    [promoted to a heading] Philip Green Inspector...". Column-clustering
    should read the left column in full before the right column, the same
    way _ordered_list_items already does for a single list group's own
    children."""
    document = {
        "texts": [
            _text_item("#/texts/0", "Terms of Reference", 40, 100, 120),
            _text_item("#/texts/1", "Acknowledgements", 300, 100, 120),
            _text_item(
                "#/texts/2", "To review the provisions of the Bail Act 1977...", 40, 155, 185
            ),
            _text_item("#/texts/3", "Bail Advisory Committee", 300, 155, 165),
            _text_item(
                "#/texts/4", "Philip Green Inspector, Victoria Police", 300, 170, 187
            ),
            _text_item("#/texts/5", "the presumption of innocence", 40, 193, 291),
            _text_item("#/texts/6", "Mark Higginbotham", 300, 192, 201),
        ],
        "pages": {"1": {"size": {"width": 600, "height": 800}}},
    }
    all_items = {str(item["self_ref"]): item for item in document["texts"]}

    ordered = KonverterPipeline._ordered_document_references(document, all_items)

    assert ordered == [
        "#/texts/0",
        "#/texts/2",
        "#/texts/5",
        "#/texts/1",
        "#/texts/3",
        "#/texts/4",
        "#/texts/6",
    ]


def test_single_column_page_order_is_left_completely_untouched():
    """The column-clustering fix above must stay inert on the vast
    majority of pages, which are genuinely single-column — reordering a
    page nothing is actually wrong with is pure regression risk."""
    document = {
        "texts": [
            _text_item("#/texts/0", "Introduction", 40, 100, 120),
            _text_item("#/texts/1", "This report examines...", 40, 130, 160),
            _text_item("#/texts/2", "The commission also considered...", 40, 165, 195),
            _text_item("#/texts/3", "Finally, the report recommends...", 40, 200, 230),
        ],
        "pages": {"1": {"size": {"width": 600, "height": 800}}},
    }
    all_items = {str(item["self_ref"]): item for item in document["texts"]}

    ordered = KonverterPipeline._ordered_document_references(document, all_items)

    assert ordered == ["#/texts/0", "#/texts/1", "#/texts/2", "#/texts/3"]


def test_single_stray_offcolumn_item_does_not_trigger_reordering():
    """A lone off-column element — a caption, a pull-quote, a page number
    that slipped past the header/footer filter — must never register as a
    second column on its own; only two clusters that each carry a
    meaningful share of the page's items count as a genuine two-column
    layout."""
    document = {
        "texts": [
            _text_item("#/texts/0", "Introduction", 40, 100, 120),
            _text_item("#/texts/1", "This report examines...", 40, 130, 160),
            _text_item("#/texts/2", "The commission also considered...", 40, 165, 195),
            _text_item("#/texts/3", "Finally, the report recommends...", 40, 200, 230),
            _text_item("#/texts/4", "Figure 1", 320, 130, 140),
        ],
        "pages": {"1": {"size": {"width": 600, "height": 800}}},
    }
    all_items = {str(item["self_ref"]): item for item in document["texts"]}

    ordered = KonverterPipeline._ordered_document_references(document, all_items)

    assert ordered == [
        "#/texts/0",
        "#/texts/1",
        "#/texts/2",
        "#/texts/3",
        "#/texts/4",
    ]


def test_already_column_ordered_page_is_left_untouched():
    """If Docling's own order already reads the left column in full before
    the right column, there's nothing to fix — reordering an already-correct
    page is pure risk with no benefit, so the switches-vs-clusters check
    should leave it exactly as it was."""
    document = {
        "texts": [
            _text_item("#/texts/0", "Terms of Reference", 40, 100, 120),
            _text_item("#/texts/1", "To review the provisions...", 40, 155, 185),
            _text_item("#/texts/2", "the presumption of innocence", 40, 193, 291),
            _text_item("#/texts/3", "Acknowledgements", 300, 100, 120),
            _text_item("#/texts/4", "Bail Advisory Committee", 300, 155, 165),
            _text_item("#/texts/5", "Philip Green Inspector", 300, 170, 187),
        ],
        "pages": {"1": {"size": {"width": 600, "height": 800}}},
    }
    all_items = {str(item["self_ref"]): item for item in document["texts"]}

    ordered = KonverterPipeline._ordered_document_references(document, all_items)

    assert ordered == [
        "#/texts/0",
        "#/texts/1",
        "#/texts/2",
        "#/texts/3",
        "#/texts/4",
        "#/texts/5",
    ]
