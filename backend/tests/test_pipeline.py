from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF, used only to build test fixture PDFs with real text

from app.config import Settings
from app.pipeline import (
    KonverterPipeline,
    _is_genuine_form_content,
    _merge_indented_footnote_continuations,
    _relabel_footnote_lists,
    _relabel_misclassified_page_furniture,
    _reorder_inverted_adjacent_footnotes,
    _repair_split_footnote_markers,
    _split_merged_footnotes,
    _synthesize_missing_pictures,
)


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


def test_recommendations_citing_a_named_act_inside_a_callout_panel_are_not_relabelled_footnote():
    """Real bug found live in "Neighbourhood Tree Disputes": a genuine
    3-item recommendations panel -- "53 The Act should state...", "54 ...
    Sale of Land Act 1962 (Vic) should be amended...", "55 The Sale of
    Land Act 1962 (Vic) should be amended..." -- got relabelled "footnote"
    and rendered with role="doc-footnote" purely because 2 of 3 entries
    cite a specific "(Vic)" Act, the same vocabulary a genuine citation
    uses. A recommendation to amend a named Act is extremely common in
    this corpus and can't be told apart from a citation by vocabulary
    alone -- but a genuine footnote never prints inside a visually
    detected, bordered/shaded callout panel the way a real recommendations
    box does, so a list already sitting inside one of detect_callout_
    regions' own regions is left alone regardless of what it cites."""
    entries = [
        _entry("53 The Act should state that purchasers should be notified of any legal action."),
        _entry("54 The Due Diligence Checklist under the Sale of Land Act 1962 (Vic) should be amended."),
        _entry("55 The Sale of Land Act 1962 (Vic) should be amended to include a provision."),
    ]
    bounds = {"left": 79.6, "top": 123.2, "right": 518.0, "bottom": 467.5}
    blocks = [_list_block(entries, page=3, source_bounds=bounds)]
    callout_regions = [{"page": 3, "left": 60.0, "top": 100.0, "right": 540.0, "bottom": 500.0}]

    result = _relabel_footnote_lists(blocks, callout_regions)

    assert result == blocks
    assert all(block["label"] == "list" for block in result)


def test_recommendations_citing_a_named_act_outside_any_callout_are_recognised_by_directive_phrasing():
    """The narrower, harder half of the same real bug: each recommendation
    in this corpus also gets restated in running body text (its own
    chapter discusses it in detail), not just inside its summary
    box_section panel -- and *there*, there's no callout region to check
    position against at all. What still tells a genuine recommendation
    apart from a citation using the same "(Vic)" vocabulary: a
    recommendation, without exception, opens with its own directive near
    the very start -- "The Criminal Procedure Act 2009 (Vic) should be
    amended to...", "Magistrates should be required to..." -- naming the
    Act/section/body first, then immediately stating what should happen.
    A genuine footnote can use identical phrasing, but only buried inside
    a *reported* opinion, never within the first ~100 characters (real
    shape: "142 Also submissions 11, 39. The OPP noted that the right of
    arrest ... should be retained" -- the directive sits at offset 273,
    not under 90 like every real recommendation found)."""
    entries = [
        _entry(
            "8 The Criminal Procedure Act 2009 (Vic) should be amended to require the "
            "Director of Public Prosecutions to assess disclosure."
        ),
        _entry(
            "9 The Criminal Procedure Act 2009 (Vic) should be amended to require that a "
            "case direction notice is filed before committal."
        ),
    ]
    blocks = [_list_block(entries)]

    result = _relabel_footnote_lists(blocks)

    assert result == blocks
    assert all(block["label"] == "list" for block in result)


def test_a_footnote_reporting_a_stakeholders_view_is_still_recognised_despite_directive_wording():
    entries = [
        _entry(
            "142 Also submissions 11, 39. The OPP noted that the right of arrest without a "
            "warrant in these circumstances should be retained."
        ),
        _entry("143 Ibid, submission 40."),
    ]
    blocks = [_list_block(entries)]

    result = _relabel_footnote_lists(blocks)

    assert all(block["label"] == "footnote" for block in result)


def _doc_item(self_ref: str, label: str, text: str, page: int = 1) -> dict:
    return {"self_ref": self_ref, "label": label, "text": text, "prov": [{"page_no": page}]}


def test_main_title_reference_prefers_the_real_title_over_front_matter_boilerplate():
    """Real bug found live in 9 of 11 corpus documents: this function
    ranks title/section_header candidates on the first few pages almost
    entirely by how close their length is to a "title-shaped" 18-120
    characters -- so once the obviously-excluded front-matter headings
    (Contents, Preface, ...) are screened out, whichever boilerplate line
    happens to be closest to that length wins outright. In "Review of the
    Bail Act", a National Library Cataloguing-in-Publication notice (57
    characters, page 2) outscored the real title "Review of the Bail Act
    Final Report" (36 characters, page 3) purely on length, even though
    Docling gave both the identical raw "section_header" label. The
    consequence isn't cosmetic: this reference is excluded from the
    document's own body content and drives a "Title structure needs
    confirmation" review item -- so the queue told a reviewer a catalogue
    notice was the document's title, while the real title text was left
    free to be swept into ordinary heading classification instead."""
    all_items = {
        "#/texts/45": _doc_item("#/texts/45", "section_header", "Published by the Victorian Law Reform Commission", page=2),
        "#/texts/51": _doc_item("#/texts/51", "section_header", "National Library of Australia Cataloguing-in-Publication", page=2),
        "#/texts/61": _doc_item("#/texts/61", "section_header", "Review of the Bail Act Final Report", page=3),
        "#/texts/67": _doc_item("#/texts/67", "section_header", "Contents", page=4),
    }
    ordered_references = ["#/texts/45", "#/texts/51", "#/texts/61", "#/texts/67"]

    reference = KonverterPipeline._main_title_reference(all_items, ordered_references)

    assert reference == "#/texts/61"


def test_main_title_reference_returns_none_rather_than_a_publisher_contact_block():
    """The narrower half of the same bug: a document whose only page-<=5
    title/section_header candidates are boilerplate (no genuine title
    text was raw-labelled "title" or "section_header" at all, matching
    the real "Committals" shape) should end up with no chosen reference
    rather than confidently excluding a phone/fax contact block as if it
    were the title -- record["title"] (human-confirmed, required before
    approval) is always used for the actual displayed title regardless,
    so a safe "none found" is strictly better than a wrong, confident
    guess that also generates a misleading review item."""
    all_items = {
        "#/texts/1": _doc_item("#/texts/1", "section_header", "report GPO Box 4637 Melbourne Victoria 3001 Australia", page=1),
        "#/texts/25": _doc_item("#/texts/25", "section_header", "This publication of the Victorian Law Reform Commission", page=2),
        "#/texts/40": _doc_item("#/texts/40", "section_header", "Australia Telephone +61 3 8608 7800 Freecall 1300 666 555", page=2),
        "#/texts/167": _doc_item("#/texts/167", "section_header", "Contents", page=4),
    }
    ordered_references = ["#/texts/1", "#/texts/25", "#/texts/40", "#/texts/167"]

    reference = KonverterPipeline._main_title_reference(all_items, ordered_references)

    assert reference is None


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


def _footnote_block(ref: str, text: str, page: int = 28) -> dict[str, object]:
    return {"id": ref, "label": "footnote", "text": text, "page": page, "confidence": 0.9}


def _text_block(ref: str, text: str, page: int = 28) -> dict[str, object]:
    return {"id": ref, "label": "text", "text": text, "page": page, "confidence": 0.85}


def test_single_split_footnote_marker_is_reunited_with_its_content():
    """Reproduces a real VLRC bug found live in "Funeral and Burial
    Instructions": footnote 2's own number split off into its own block
    ("2", label "text"), immediately followed by its citation text
    ("Leeburn v Derndorfer (2004) 14 VR 100, 104", also label "text") --
    neither block ever reached the footnotes list; both rendered as
    ordinary visible body paragraphs sandwiched between footnotes 1 and 3."""
    blocks = [
        _footnote_block("#/texts/451", "1 Smith v Tamworth City Council (1997) 41 NSWLR 680"),
        _text_block("#/texts/452", "2"),
        _text_block("#/texts/453", "Leeburn v Derndorfer (2004) 14 VR 100, 104"),
        _footnote_block("#/texts/454", "3 Milanka Sullivan v Public Trustee"),
    ]

    repaired = _repair_split_footnote_markers(blocks)

    assert [b["id"] for b in repaired] == ["#/texts/451", "#/texts/453", "#/texts/454"]
    reunited = repaired[1]
    assert reunited["label"] == "footnote"
    assert reunited["text"] == "2 Leeburn v Derndorfer (2004) 14 VR 100, 104"


def test_run_of_split_markers_pairs_positionally_with_matching_content_run():
    """Reproduces a real VLRC bug found live in "Neighbourhood Tree
    Disputes": five consecutive footnote numbers (156-160) all split off
    into their own bare blocks, immediately followed by five citation
    blocks in the same order -- 156 pairs with the first, 160 with the
    last, then footnote 161 resumes normally with its own number intact."""
    blocks = [
        _footnote_block("#/texts/155", "155 Consultation 1 (Some Person)"),
        _text_block("#/texts/156", "156"),
        _text_block("#/texts/157", "157"),
        _footnote_block("#/texts/158", "158"),
        _text_block("#/texts/159", "159"),
        _text_block("#/texts/160", "160"),
        _footnote_block("#/texts/161a", "The falling of a branch from an otherwise healthy tree"),
        _footnote_block("#/texts/161b", "Consultation 2 (Dr Gregory Moore OAM)"),
        _footnote_block("#/texts/161c", "Consultation 4 (Participants in facilitated discussion)"),
        _text_block("#/texts/161d", "Submission 18 (ENSPEC)"),
        _footnote_block("#/texts/161e", "Submissions 7 (Ben Kenyon), 9 (Dr Karen Smith)"),
        _footnote_block("#/texts/162", "161 Consultation 6 (Ben Kenyon)"),
    ]

    repaired = _repair_split_footnote_markers(blocks)

    repaired_by_id = {b["id"]: b for b in repaired}
    assert all(
        ref not in repaired_by_id
        for ref in ["#/texts/156", "#/texts/157", "#/texts/158", "#/texts/159", "#/texts/160"]
    )
    assert repaired_by_id["#/texts/161a"]["text"] == (
        "156 The falling of a branch from an otherwise healthy tree"
    )
    assert repaired_by_id["#/texts/161a"]["label"] == "footnote"
    assert repaired_by_id["#/texts/161b"]["text"] == "157 Consultation 2 (Dr Gregory Moore OAM)"
    assert repaired_by_id["#/texts/161c"]["text"] == (
        "158 Consultation 4 (Participants in facilitated discussion)"
    )
    assert repaired_by_id["#/texts/161d"]["text"] == "159 Submission 18 (ENSPEC)"
    assert repaired_by_id["#/texts/161d"]["label"] == "footnote"
    assert repaired_by_id["#/texts/161e"]["text"] == (
        "160 Submissions 7 (Ben Kenyon), 9 (Dr Karen Smith)"
    )
    # The normal, already-correctly-numbered footnote that follows the
    # repaired run must be left completely untouched.
    assert repaired_by_id["#/texts/162"]["text"] == "161 Consultation 6 (Ben Kenyon)"


def test_unrelated_bare_number_is_never_treated_as_a_split_marker():
    """A bare number elsewhere in the document (a stray statistic, a page
    fragment) must never be mistaken for a split footnote marker just
    because it happens to be numeric -- only a number that directly
    continues the real footnote sequence qualifies."""
    blocks = [
        _footnote_block("#/texts/10", "10 Some genuine citation"),
        _text_block("#/texts/20", "20"),  # not 11 -- doesn't continue the sequence
        _text_block("#/texts/21", "Unrelated paragraph mentioning a number."),
    ]

    repaired = _repair_split_footnote_markers(blocks)

    assert repaired == blocks


def test_content_block_starting_with_an_unrelated_number_is_still_accepted():
    """Genuine footnote content can legitimately start with its own,
    unrelated number ("24 hours notice was required...") -- that must not
    be mistaken for "this block already has its own footnote number" and
    excluded from pairing."""
    blocks = [
        _footnote_block("#/texts/1", "1 Some genuine citation"),
        _text_block("#/texts/2", "2"),
        _text_block("#/texts/3", "24 hours notice was required under the relevant provision."),
        _footnote_block("#/texts/4", "3 Another genuine citation"),
    ]

    repaired = _repair_split_footnote_markers(blocks)

    repaired_by_id = {b["id"]: b for b in repaired}
    assert repaired_by_id["#/texts/3"]["text"] == (
        "2 24 hours notice was required under the relevant provision."
    )
    assert repaired_by_id["#/texts/3"]["label"] == "footnote"


def test_mismatched_marker_and_content_counts_with_no_position_data_are_left_untouched():
    """Without a real PDF's bounding boxes to fall back on (see the test
    below for the case where they're available), a mismatched marker/content
    count is genuinely ambiguous -- leave everything as-is rather than guess
    at a wrong pairing."""
    blocks = [
        _footnote_block("#/texts/1", "1 Some genuine citation"),
        _text_block("#/texts/2", "2"),
        _text_block("#/texts/3", "3"),
        _text_block("#/texts/4", "Only one piece of content follows two markers."),
        _footnote_block("#/texts/5", "4 Another genuine citation"),
    ]

    repaired = _repair_split_footnote_markers(blocks)

    assert repaired == blocks


def _positioned_block(
    label: str, ref: str, text: str, top: float, page: int = 40
) -> dict[str, object]:
    return {
        "id": ref,
        "label": label,
        "text": text,
        "page": page,
        "confidence": 0.85,
        "source_bounds": {
            "left": 79.7,
            "top": top,
            "right": 500.0,
            "bottom": top + 8.0,
            "page_width": 595.3,
            "page_height": 841.9,
        },
    }


def test_marker_whose_content_is_merged_into_its_neighbours_block_is_left_orphaned_without_corrupting_the_neighbour():
    """Reproduces a real bug found live in "Funeral and Burial Instructions":
    footnotes 16 and 17 are two separate, consecutively numbered citations
    on the printed page, but Docling ran them together into a single text
    item with no boundary between them and no "17" embedded anywhere in the
    merged text to mark where one ends and the other begins (confirmed
    directly against the source PDF: 16's own line reads "Consultations 10
    (RSL, Aged and Health Support)...", 17's reads "Information given to
    the Commission by a community member on 29 April 2014." -- two clearly
    separate footnotes Docling nonetheless fused). That left marker run
    ["16", "17"] facing only one real content block, not two. Naively
    zipping front-to-front would glue that merged block onto marker 17
    (wrong) and leave 16 unrepaired (also wrong) purely because 17, not 16,
    happens to be second in the run. What the real PDF's own coordinates
    show instead: "16" sits 0.37pt from the merged block on the page, while
    "17" sits 8pt+ away -- distances only physically possible if 16's own
    number and the merged text are two halves of the same superscripted
    line, split apart purely by Docling's layout model. Matching on that
    proximity instead of raw position correctly reunites 16 with the real
    content and leaves 17 as an honest, unrepaired orphan -- its own
    citation is genuinely in there, merged and unsplittable without a
    boundary signal that was never printed, not silently invented or
    dropped."""
    blocks = [
        _footnote_block("#/texts/698", "15 Consultation 28 (Marie Brittan)."),
        _positioned_block("text", "#/texts/699", "16", top=752.96),
        _positioned_block("text", "#/texts/700", "17", top=761.01),
        _positioned_block(
            "footnote",
            "#/texts/701",
            "Consultations 10 (RSL, Aged and Health Support), 19 (Chinese Cancer Society of Victoria).",
            top=752.59,
        ),
        _footnote_block("#/texts/707", "21 For more case studies of this nature see [5.53]."),
    ]

    repaired = _repair_split_footnote_markers(blocks)

    repaired_by_id = {b["id"]: b for b in repaired}
    assert "#/texts/699" not in repaired_by_id
    assert repaired_by_id["#/texts/701"]["label"] == "footnote"
    assert repaired_by_id["#/texts/701"]["text"] == (
        "16 Consultations 10 (RSL, Aged and Health Support), 19 (Chinese Cancer Society of Victoria)."
    )
    # 17's own content is merged into 701 with no boundary to split on --
    # it must be left as an unrepaired, honestly-orphaned bare marker rather
    # than guessed at, and the real footnote after it must resume from the
    # correct next number rather than getting confused by the gap.
    assert repaired_by_id["#/texts/700"]["label"] == "text"
    assert repaired_by_id["#/texts/700"]["text"] == "17"
    assert repaired_by_id["#/texts/707"]["text"] == "21 For more case studies of this nature see [5.53]."


def _footnote_block_at(ref: str, text: str, left: float, top: float, page: int = 40) -> dict[str, object]:
    return {
        "id": ref,
        "label": "footnote",
        "text": text,
        "page": page,
        "confidence": 0.85,
        "source_bounds": {
            "left": left,
            "top": top,
            "right": left + 300.0,
            "bottom": top - 8.0,
            "page_width": 595.3,
            "page_height": 841.9,
        },
    }


def test_wrapped_footnote_continuation_line_is_merged_not_treated_as_a_new_footnote():
    """Reproduces a real bug found live in "Neighbourhood Tree Disputes",
    spotted by the user directly ("footnote number duplicate only happen
    in this section"): footnote 161's own citation list is long enough to
    wrap onto a second printed line -- "161 Submissions 6 (Name
    withheld), 10 (Professor Phillip Hamilton), ... 27 (Name withheld),
    38 (L. Barry Wollmer); Consultation 14 (Robert Mineo)." -- and that
    wrapped line, indented the way a hanging-indent continuation always
    is, happens to start with "38", which Docling extracted as if it
    were its own separate footnote. Left alone, "38" reading as a real
    footnote number wildly out of sequence broke every other footnote's
    number display for the rest of the section (see the reordering test
    below for why one bad number cascades that far), not just this one
    citation."""
    blocks = [
        _footnote_block_at(
            "#/texts/1",
            "161 Submissions 6 (Name withheld), 10 (Professor Phillip Hamilton), 21 (Pointon Partners Lawyers), 23 (Name withheld); 27 (Name withheld),",
            left=80.19,
            top=73.25,
        ),
        _footnote_block_at(
            "#/texts/2",
            "38 (L. Barry Wollmer); Consultation 14 (Robert Mineo).",
            left=119.40,
            top=81.25,
        ),
        _footnote_block_at(
            "#/texts/3",
            "162 Submissions 12 (Dr Gregory Moore OAM), 29 (David Galwey); Consultation 14 (Robert Mineo).",
            left=80.19,
            top=65.24,
        ),
    ]

    merged = _merge_indented_footnote_continuations(blocks)

    assert [b["id"] for b in merged] == ["#/texts/1", "#/texts/3"]
    assert merged[0]["text"] == (
        "161 Submissions 6 (Name withheld), 10 (Professor Phillip Hamilton), 21 (Pointon Partners Lawyers), 23 (Name withheld); 27 (Name withheld), "
        "38 (L. Barry Wollmer); Consultation 14 (Robert Mineo)."
    )


def test_two_adjacent_same_margin_footnotes_printed_out_of_order_are_reordered():
    """Reproduces a real bug found live in "Neighbourhood Tree Disputes",
    spotted by the user directly: footnote 197 ("Consultation 10 (Baw Baw
    Shire Council).") printed physically *below* footnote 196
    ("Consultation 9 (Nillumbik Shire Council).") on the page -- both
    genuine, complete, correctly-cited footnotes, starting flush at the
    same ~80pt margin -- yet Docling's own reading-order model extracted
    them in reverse (197 before 196). preview_html.py's
    _render_footnotes_list only trusts a section's embedded numbers to
    drive the printed <li> numbering when *every* consecutive pair
    increases -- this one inverted pair fell the *entire* 203-footnote
    section back to doubled-number display, not just these two."""
    blocks = [
        _footnote_block_at("#/texts/1", "195 See Planning and Environment Act 1987 (Vic) s 46AC.", left=79.75, top=113.30),
        _footnote_block_at("#/texts/2", "197 Consultation 10 (Baw Baw Shire Council).", left=80.17, top=33.25),
        _footnote_block_at("#/texts/3", "196 Consultation 9 (Nillumbik Shire Council).", left=80.17, top=41.26),
    ]

    reordered = _reorder_inverted_adjacent_footnotes(blocks)

    assert [b["id"] for b in reordered] == ["#/texts/1", "#/texts/3", "#/texts/2"]


def test_wrapped_continuation_that_looks_like_it_could_reorder_is_never_swapped_instead():
    """A wrapped continuation line indented well past the footnote
    margin (see the merge test above) must never be mistaken for a
    genuine transposed footnote by the reordering check -- their numbers
    can look just as sequentially reversed, but only a same-margin pair
    is a real transposition; an indented one is a continuation that
    still needs merging, not swapping."""
    blocks = [
        _footnote_block_at(
            "#/texts/1",
            "3 This is subject to the qualification that ashes should be treated with appropriate respect and reverence.",
            left=79.70,
            top=65.30,
        ),
        _footnote_block_at(
            "#/texts/2",
            "4 BMLR 140; Smith v Tamworth City Council (1997) 41 NSWLR 680.",
            left=119.20,
            top=73.26,
        ),
    ]

    reordered = _reorder_inverted_adjacent_footnotes(blocks)

    assert [b["id"] for b in reordered] == ["#/texts/1", "#/texts/2"]


def test_two_footnotes_merged_into_one_block_are_split_apart():
    """Reproduces a real bug found live in "Funeral and Burial
    Instructions", caught by the user directly, not by this session's own
    scan: footnote 7's number and citation were buried mid-sentence inside
    footnote 6's own block ("...Keller v Keller (2007) 15 VR 667 [6]. 7
    Laing v Laing [2014] QSC 194 [20]") -- footnote 7 was never its own
    block, so it never got its own footnotes-list entry, and its reader-
    facing marker rendered as plain unlinked text instead of a proper
    footnote reference."""
    blocks = [
        _footnote_block(
            "#/texts/457",
            "6 Smith v Tamworth City Council (1997) 41 NSWLR 680, 693; "
            "Keller v Keller (2007) 15 VR 667 [6]. 7 Laing v Laing [2014] QSC 194 [20]",
        ),
    ]

    result = _split_merged_footnotes(blocks)

    assert len(result) == 2
    assert result[0]["id"] == "#/texts/457"
    assert result[0]["text"] == (
        "6 Smith v Tamworth City Council (1997) 41 NSWLR 680, 693; "
        "Keller v Keller (2007) 15 VR 667 [6]."
    )
    assert result[0]["label"] == "footnote"
    assert result[1]["text"] == "7 Laing v Laing [2014] QSC 194 [20]"
    assert result[1]["label"] == "footnote"


def test_chain_of_three_merged_footnotes_splits_into_three_blocks():
    blocks = [
        _footnote_block(
            "#/texts/11",
            "11 Queensland Law Reform Commission, Final Report No 69 (2011). "
            "12 Law Commission (New Zealand), Reforming the Law (2019). "
            "13 Ibid 45.",
        ),
    ]

    result = _split_merged_footnotes(blocks)

    assert [b["text"] for b in result] == [
        "11 Queensland Law Reform Commission, Final Report No 69 (2011).",
        "12 Law Commission (New Zealand), Reforming the Law (2019).",
        "13 Ibid 45.",
    ]
    assert all(b["label"] == "footnote" for b in result)


def test_coincidental_period_number_capital_is_not_split_when_out_of_sequence():
    """A citation's own page pinpoint or clause number followed by a
    capital letter must never be mistaken for the start of the next
    footnote -- only a number that's exactly one more than this block's
    own footnote number qualifies."""
    blocks = [
        _footnote_block(
            "#/texts/1",
            "1 Some Act 1958 (Vic) s 5. 42 per cent of respondents disagreed.",
        ),
    ]

    result = _split_merged_footnotes(blocks)

    assert result == blocks


def test_non_footnote_blocks_are_never_touched_by_footnote_splitting():
    blocks = [
        _text_block("#/texts/1", "1 This is not a footnote. 2 Neither is this."),
    ]

    result = _split_merged_footnotes(blocks)

    assert result == blocks


def _furniture_item(ref: str, text: str, label: str, page: int) -> dict[str, object]:
    return {
        "self_ref": ref,
        "label": label,
        "text": text,
        "prov": [{"page_no": page, "bbox": {"l": 80, "t": 780, "r": 400, "b": 800}}],
    }


def test_unique_footnote_citation_mislabelled_page_footer_is_recovered():
    """Real shape found across the corpus: Docling's layout model labels
    any item sitting in the page's bottom margin "page_footer" purely by
    position -- a genuine footnote citation sitting there (this is where
    footnotes print) gets the same label as an actual running footer, and
    every downstream consumer trusts that label completely, silently
    dropping the citation before a reviewer ever sees it. A citation that
    appears only once in the whole document cannot be a *running* footer
    by definition -- there's nothing for it to run across."""
    document = {
        "texts": [
            _furniture_item(
                "#/texts/1",
                "Consultation 4 (Victorian Criminal Bar Association).",
                "page_footer",
                12,
            ),
            _furniture_item("#/texts/2", "208", "page_footer", 12),
        ]
    }

    _relabel_misclassified_page_furniture(document)

    assert document["texts"][0]["label"] == "text"
    # A bare page number is unambiguous furniture regardless of repetition.
    assert document["texts"][1]["label"] == "page_footer"


def test_page_number_mislabelled_plain_text_is_recognised_without_swallowing_a_real_footnote_marker():
    """Real bug found live in "Birth Registration and Birth Certificates",
    spotted directly by the user in a rendered preview: a lone, floating
    "8" sitting between two body paragraphs with no sentence around it.
    Docling's layout model had failed to tag this page's own running page
    number as "page_footer" at all -- unlike every other page in the same
    document, where the identically-shaped page number was correctly
    tagged and excluded -- leaving it raw-labelled plain "text" and never
    reaching the furniture-recovery logic above, which only ever looks at
    items Docling itself already called page_header/page_footer.

    The margin-position band alone can't tell a stray page number apart
    from a split-off footnote marker -- both sit in the same bottom-margin
    region, since a footnote apparatus fills that whole area. What can:
    this document's own confirmed, correctly-labelled page numbers all
    print flush against the page's left edge (left=0), while every
    footnote marker in the same document is indented to the footnote
    block's own margin (~79pt or more) -- requiring that edge-flush
    position, not just the margin band, is what keeps a genuine,
    still-repairable footnote marker (like "9" here, indented) from ever
    being mistaken for a page number."""
    document = {
        "pages": {"28": {"size": {"height": 841.89, "width": 595.28}}},
        "texts": [
            # The real page-edge page number Docling mislabelled "text".
            {
                "self_ref": "#/texts/432",
                "label": "text",
                "text": "8",
                "prov": [{"page_no": 28, "bbox": {"l": 0.0, "t": 36.13, "r": 42.25, "b": 27.48}}],
            },
            # A genuine, still-repairable split-off footnote marker on the
            # same page, indented to the footnote block's own margin --
            # must be left completely alone by this check.
            {
                "self_ref": "#/texts/427",
                "label": "text",
                "text": "9",
                "prov": [{"page_no": 28, "bbox": {"l": 79.7, "t": 48.93, "r": 82.4, "b": 44.35}}],
            },
        ],
    }

    _relabel_misclassified_page_furniture(document)

    assert document["texts"][0]["label"] == "page_footer"
    assert document["texts"][1]["label"] == "text"


def test_appendix_letter_margin_indicator_mislabelled_plain_text_is_recognised():
    """Real bug found live in the same "check all the labels" spirit,
    spotted while auditing high-confidence blocks for false positives that
    skip review entirely: a lone "B" sitting immediately before its own
    "Appendix B: Consultations" heading, with no sentence around it --
    the same visible shape as the page-number bug above, but Docling had
    raw-labelled it plain "text" this time instead of "page_footer".
    Confirmed directly against the source PDF: the *identical* bounding
    box for this "B" repeats on every page of Appendix B, and a sibling
    document processed from the same source PDF has the exact same glyph
    correctly raw-labelled "page_header" by Docling -- the same real
    content, inconsistently classified by Docling itself, purely because
    a margin indicator sits within the page's corner margin rather than
    flush at left=0 the way a page number does."""
    document = {
        "pages": {"143": {"size": {"height": 841.89, "width": 595.28}}},
        "texts": [
            # The real margin-indicator letter Docling mislabelled "text",
            # sitting in the top-right corner margin (~40pt from the edge,
            # not flush, but still well outside the ~79pt body margin).
            {
                "self_ref": "#/texts/900",
                "label": "text",
                "text": "B",
                "prov": [{"page_no": 143, "bbox": {"l": 540.5, "t": 795.8, "r": 552.3, "b": 779.0}}],
            },
            # A genuine, still-repairable split-off footnote marker on the
            # same page, indented to the footnote block's own margin --
            # must be left completely alone by this check.
            {
                "self_ref": "#/texts/901",
                "label": "text",
                "text": "3",
                "prov": [{"page_no": 143, "bbox": {"l": 79.7, "t": 48.93, "r": 82.4, "b": 44.35}}],
            },
        ],
    }

    _relabel_misclassified_page_furniture(document)

    assert document["texts"][0]["label"] == "page_header"
    assert document["texts"][1]["label"] == "text"


def _write_pdf_with_images(path: Path, decorative_pages: int, unique_page_rect: tuple) -> None:
    """A multi-page PDF where the first `decorative_pages` pages carry the
    exact same embedded image (PyMuPDF dedupes identical pixmaps to one
    shared xref, exactly like a real repeating background graphic would
    reuse one embedded image object across a report's chapter-opener
    pages), and the final page carries a distinct, unique image -- the
    real shape found live: a repeating decorative graphic versus a
    genuine, one-off figure Docling never detected as a picture."""
    doc = fitz.open()
    for _ in range(decorative_pages + 1):
        doc.new_page(width=595, height=842)
    decorative = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    decorative.set_rect(decorative.irect, (200, 50, 50))
    unique = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    unique.set_rect(unique.irect, (50, 200, 50))
    for page_index in range(decorative_pages):
        doc[page_index].insert_image(fitz.Rect(100, 100, 300, 300), pixmap=decorative)
    doc[decorative_pages].insert_image(fitz.Rect(*unique_page_rect), pixmap=unique)
    doc.save(path)
    doc.close()


def test_a_genuine_one_off_image_docling_never_detected_is_synthesized_as_a_picture(tmp_path):
    """Reproduces a real bug found live in "Funeral and Burial Instructions",
    spotted directly by the user: "Figure 2: Excerpt from the Hindu
    Community Council of Victoria's 'My Wish' form" (page 95) has a real,
    correctly-captioned reference in the body text, but Docling's own
    `pictures` list has zero entries anywhere near it -- confirmed live,
    the same was true of the neighbouring Figure 1 and Figure 3 on pages
    93 and 96. All three are genuine, unique embedded images the PDF
    itself unambiguously contains; Docling's picture-detection model
    simply missed them, so nothing downstream ever had anything to render.
    A decorative graphic repeating across many pages (found live in
    "Review of the Bail Act", 56 pages of one recurring chapter-opener
    image) must never be swept up the same way."""
    pdf_path = tmp_path / "source.pdf"
    _write_pdf_with_images(pdf_path, decorative_pages=3, unique_page_rect=(120, 150, 420, 450))
    document = {"pictures": []}

    _synthesize_missing_pictures(document, pdf_path)

    pictures = document["pictures"]
    assert len(pictures) == 1
    synthesized = pictures[0]
    assert synthesized["label"] == "picture"
    assert synthesized["prov"][0]["page_no"] == 4
    bbox = synthesized["prov"][0]["bbox"]
    assert bbox["coord_origin"] == "BOTTOMLEFT"
    # PyMuPDF's own rect was (120, 150, 420, 450) in top-left coordinates;
    # converted to Docling's bottom-left convention on an 842pt-tall page.
    assert bbox["l"] == 120
    assert bbox["r"] == 420
    assert bbox["t"] == 842 - 150
    assert bbox["b"] == 842 - 450


def test_a_repeating_decorative_graphic_is_never_mistaken_for_a_missing_figure(tmp_path):
    """The same repetition signal already trusted for running text
    furniture applies to images: an embedded picture whose exact content
    (xref) recurs 3 or more times across the document is decoration, not
    a genuine missing figure, regardless of how large it is or how many
    pages Docling has no picture entry for."""
    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    for _ in range(4):
        doc.new_page(width=595, height=842)
    decorative = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    decorative.set_rect(decorative.irect, (200, 50, 50))
    for page_index in range(4):
        doc[page_index].insert_image(fitz.Rect(100, 100, 300, 300), pixmap=decorative)
    doc.save(pdf_path)
    doc.close()
    document = {"pictures": []}

    _synthesize_missing_pictures(document, pdf_path)

    assert document["pictures"] == []


def test_recovered_item_with_its_own_footnote_number_is_labelled_footnote_not_text():
    """A recovered page_footer item that itself has a bare leading number
    (no "." or ")" after it, the same shape Docling's own genuine footnote
    items have) plus dominant citation vocabulary is a footnote in its own
    right, not generic paragraph text -- labelling it "footnote" here (not
    just "text") lets _split_merged_footnotes and _repair_split_footnote_
    markers, both keyed on label=="footnote", still repair it further down
    the same pipeline exactly as they would for one Docling got right from
    the start. An item with no leading number of its own is left as plain
    "text" rather than guessed at."""
    document = {
        "texts": [
            _furniture_item("#/texts/1", "137 Consultation 9 (Victorian Bar).", "page_footer", 40),
            _furniture_item(
                "#/texts/2",
                "The original terms of reference stated section 46(1) which should read section 49.",
                "page_footer",
                41,
            ),
        ]
    }

    _relabel_misclassified_page_furniture(document)

    assert document["texts"][0]["label"] == "footnote"
    assert document["texts"][1]["label"] == "text"


def test_genuine_running_header_repeated_across_many_pages_is_left_alone():
    document = {
        "texts": [
            _furniture_item(
                f"#/texts/{page}",
                "Victorian Law Reform Commission Contempt of Court: Report",
                "page_header",
                page,
            )
            for page in range(1, 6)
        ]
    }

    _relabel_misclassified_page_furniture(document)

    assert all(item["label"] == "page_header" for item in document["texts"])


def test_citation_repeatedly_footnoted_but_occasionally_mislabelled_page_footer_is_still_recovered():
    """Real bug found live in "Contempt of Court": a short citation like
    "Submission 22 (Law Institute of Victoria)." gets footnoted dozens of
    times throughout a long chapter -- so it also recurs verbatim, exactly
    the signal this function otherwise trusts completely to mean "running
    furniture, not content". A handful of those same recurring citations
    happened to lose their footnote number and get raw-labelled
    "page_footer" by Docling on 3+ pages, meeting the repeats-3+ bar and
    getting left alone as if they were the report's own running title --
    silently dropping a real, substantive citation the exact same text is
    elsewhere correctly footnoted as. What tells a repeating *citation*
    apart from a repeating *disclaimer*: Docling's own footnote labelling
    of the identical text elsewhere in the same document. A text this
    function is about to wave through as furniture that Docling itself
    already labelled "footnote" somewhere else is a footnote, not
    furniture, regardless of how many times it repeats."""
    document = {
        "texts": [
            _furniture_item("#/texts/1", "62 Submission 22 (Law Institute of Victoria).", "footnote", 53),
            _furniture_item("#/texts/2", "36 Submission 22 (Law Institute of Victoria).", "footnote", 71),
            _furniture_item("#/texts/3", "Submission 22 (Law Institute of Victoria).", "page_footer", 56),
            _furniture_item("#/texts/4", "Submission 22 (Law Institute of Victoria).", "page_footer", 128),
            _furniture_item("#/texts/5", "Submission 22 (Law Institute of Victoria).", "page_footer", 142),
        ]
    }

    _relabel_misclassified_page_furniture(document)

    assert document["texts"][0]["label"] == "footnote"
    assert document["texts"][1]["label"] == "footnote"
    assert document["texts"][2]["label"] == "text"
    assert document["texts"][3]["label"] == "text"
    assert document["texts"][4]["label"] == "text"


def test_furniture_recurring_only_twice_is_not_confidently_running_and_is_recovered():
    """Two occurrences isn't enough to trust as a genuine running header --
    a real one recurs on every page of its section, not just twice in a
    500-page document -- so this stays conservative in the direction of
    recovering real content rather than over-trusting a coincidental
    repeat."""
    document = {
        "texts": [
            _furniture_item("#/texts/1", "See Appendix D for a list of these cases.", "page_footer", 40),
            _furniture_item("#/texts/2", "See Appendix D for a list of these cases.", "page_footer", 41),
        ]
    }

    _relabel_misclassified_page_furniture(document)

    assert all(item["label"] == "text" for item in document["texts"])


def test_bare_page_numbers_and_roman_numerals_are_always_left_as_furniture():
    document = {
        "texts": [
            _furniture_item("#/texts/1", "xxv", "page_footer", 5),
            _furniture_item("#/texts/2", "102 108", "page_footer", 6),
            _furniture_item("#/texts/3", "3", "page_header", 3),
        ]
    }

    _relabel_misclassified_page_furniture(document)

    assert all(
        item["label"] in {"page_footer", "page_header"} for item in document["texts"]
    )


def test_genuine_survey_form_is_recognised_as_a_form():
    text = (
        "Question 1\nHave you planned your funeral and burial?\nNo\n"
        "Yes (Skip to Question 3)"
    )
    assert _is_genuine_form_content(text) is True

    text = (
        "AGENT:\nName:\nAddress:\nTelephone Number:\n"
        "Signature Indicating Acceptance of Appointment:"
    )
    assert _is_genuine_form_content(text) is True


def test_glossary_and_legislation_list_swept_into_a_form_area_are_recognised_as_not_a_form():
    """Real shapes found across the corpus: Docling's "form_area"/
    "key_value_area" grouping is a purely visual classification (short,
    discrete lines, similar to a form's own layout) with no regard for
    content -- a glossary's term-then-definition lines, a Table of
    Legislation, a Table of Cases, and a Commission Chair's signature
    block were all being swept into label "form" and rendered as a
    confusing "Form fields" checkbox-style group instead of their real
    structure."""
    glossary = (
        "Investigating agency\nThe agency investigating a criminal offence. "
        "This is often Victoria Police but can also be other agencies such "
        "as WorkSafe Victoria."
    )
    assert _is_genuine_form_content(glossary) is False

    legislation = (
        "Bail Act 1977 (Vic)\n"
        "Charter of Human Rights and Responsibilities Act 2006 (Vic)"
    )
    assert _is_genuine_form_content(legislation) is False

    cases = (
        "Advan Investments Pty Ltd v Dean Gleeson Motor Sales Pty Ltd [2003] VSC 201\n"
        "A-G (Vic) v Rich [1998] 19 ACSC 260"
    )
    assert _is_genuine_form_content(cases) is False

    signature = "The Hon. P.D. Cummins AM Chair, Victorian Law Reform Commission September 2016"
    assert _is_genuine_form_content(signature) is False


def test_an_unrecognised_raw_docling_label_falls_back_to_text_not_unspecified():
    """"unspecified" is no longer a label the product surfaces. Real shape
    found in the corpus: a Table of Cases citation list Docling tagged
    "code" (an odd but real mapping gap, not the more common page_footer/
    form_area false positives already fixed elsewhere) -- any raw label
    _blocks_from_document's own mapping doesn't recognise must land as
    "text", the same real, reviewable structure label it already renders
    as, rather than a dead-end "unspecified" category."""
    pipe = KonverterPipeline(_settings())
    document = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "code",
                "text": "Advan Investments Pty Ltd v Dean Gleeson Motor Sales Pty Ltd [2003] VSC 201",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {"l": 40, "t": 100, "r": 240, "b": 120, "coord_origin": "TOPLEFT"},
                    }
                ],
            },
        ],
        "pages": {"1": {"size": {"width": 600, "height": 800}}},
    }

    blocks, warnings = pipe._blocks_from_document(document, {}, None)

    matching = [block for block in blocks if "Advan Investments" in block.get("text", "")]
    assert len(matching) == 1
    assert matching[0]["label"] == "text"
