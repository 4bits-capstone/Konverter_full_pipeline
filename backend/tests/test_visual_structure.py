from __future__ import annotations

from app.exporter import build_publication
from app.visual_structure import _span_is_artifact, group_quote_blocks, group_visual_callouts


def source_bounds(top: float, bottom: float) -> dict:
    return {
        "left": 100,
        "top": top,
        "right": 500,
        "bottom": bottom,
        "page_width": 595,
        "page_height": 842,
    }


def test_visual_panel_becomes_one_semantic_recommendations_box_section():
    blocks = [
        {
            "id": "before",
            "label": "text",
            "text": "Before panel",
            "page": 52,
            "order": 0,
            "source_bounds": source_bounds(300, 340),
        },
        {
            "id": "heading",
            "label": "section_header_3",
            "text": "! RECOMMENDATIONS",
            "page": 52,
            "order": 1,
            "source_bounds": source_bounds(404, 414),
        },
        {
            "id": "items",
            "label": "list",
            "text": "1. First recommendation\n2. Second recommendation",
            "list_entries": [
                {"text": "First recommendation", "marker": "1.", "enumerated": True},
                {"text": "Second recommendation", "marker": "2.", "enumerated": True},
            ],
            "page": 52,
            "order": 2,
            "source_bounds": source_bounds(436, 600),
        },
    ]
    region = {
        "page": 52,
        "left": 90,
        "top": 398,
        "right": 504,
        "bottom": 638,
        "page_width": 595,
        "page_height": 842,
    }

    grouped = group_visual_callouts(blocks, [region])

    assert [block["id"] for block in grouped] == ["before", "box-section:heading"]
    box_section = grouped[1]
    assert box_section["box_section_title"] == "RECOMMENDATIONS"
    assert box_section["box_section_kind"] == "recommendations"
    assert box_section["box_section_blocks"][0]["list_entries"][0]["marker"] == "1."


def test_visual_quote_reaches_publication_as_a_quote_block():
    blocks = [
        {
            "id": "quote-text",
            "label": "text",
            "text": "Quoted statement.",
            "page": 3,
            "order": 0,
            "source_bounds": source_bounds(300, 350),
        },
        {
            "id": "quote-speaker",
            "label": "text",
            "text": "Speaker attribution",
            "page": 3,
            "order": 1,
            "source_bounds": source_bounds(360, 390),
        },
    ]
    region = {
        "page": 3,
        "left": 90,
        "top": 280,
        "right": 510,
        "bottom": 410,
        "page_width": 595,
        "page_height": 842,
    }

    grouped = group_quote_blocks(blocks, [region])
    assert len(grouped) == 1
    assert grouped[0]["label"] == "quote"

    publication = build_publication(
        grouped,
        {"title": "Example report", "pages": 3, "file_name": "example.pdf"},
    )
    assert publication["sections"][0]["blocks"][0] == {
        "type": "quote",
        "text": "Quoted statement.\n\nSpeaker attribution",
        "page": 3,
    }


def test_toc_derived_chapter_heading_is_not_swallowed_by_decorative_panel():
    blocks = [
        {
            "id": "chapter",
            "label": "section_header_1",
            "text": "1. Introduction",
            "toc_derived": True,
            "page": 25,
            "order": 0,
            "source_bounds": source_bounds(300, 340),
        },
        {
            "id": "local-contents",
            "label": "list",
            "text": "2 Terms of reference\n7 The approach of the Commission",
            "page": 25,
            "order": 1,
            "source_bounds": source_bounds(360, 500),
        },
    ]
    region = {
        "page": 25,
        "left": 90,
        "top": 290,
        "right": 504,
        "bottom": 520,
        "page_width": 595,
        "page_height": 842,
    }

    grouped = group_visual_callouts(blocks, [region])

    assert [block["id"] for block in grouped] == ["chapter", "local-contents"]


def test_box_section_reaches_preview_with_semantic_child_content():
    publication = build_publication(
        [
            {
                "id": "title",
                "label": "title",
                "text": "Example report",
                "page": 1,
                "order": 0,
            },
            {
                "id": "chapter",
                "label": "section_header_1",
                "text": "1. Findings",
                "page": 2,
                "order": 1,
            },
            {
                "id": "box-section",
                "label": "box_section",
                "text": "First recommendation",
                "box_section_title": "Recommendations",
                "box_section_kind": "recommendations",
                "box_section_blocks": [
                    {
                        "label": "list",
                        "page": 2,
                        "list_entries": [
                            {
                                "text": "First recommendation",
                                "marker": "4.",
                                "enumerated": True,
                            }
                        ],
                    },
                    {
                        "id": "boxed-table",
                        "label": "table",
                        "page": 2,
                        "table_data": {
                            "caption": "Recommendation status",
                            "headers": ["Item", "Status"],
                            "rows": [["First", "Open"]],
                        },
                    },
                ],
                "page": 2,
                "order": 2,
            },
        ],
        {"title": "Example report", "pages": 2, "file_name": "example.pdf"},
    )

    box_section = publication["sections"][0]["blocks"][0]
    assert box_section["type"] == "box_section"
    assert box_section["variant"] == "recommendations"
    assert box_section["blocks"][0]["type"] == "list"
    assert box_section["blocks"][0]["style"] == "ordered"
    assert box_section["blocks"][0]["start"] == 4
    assert box_section["blocks"][1]["type"] == "table"
    assert box_section["blocks"][1]["caption"] == "Recommendation status"


def test_large_low_contrast_chapter_number_is_an_artifact():
    assert _span_is_artifact(
        "3",
        146.4,
        (255, 255, 255),
        1.0,
        (1.0, 0.0),
        (92.7, -5.8, 170.3, 172.8),
        595,
        842,
    )


def test_normal_body_text_is_not_an_artifact():
    assert not _span_is_artifact(
        "This is ordinary body text.",
        11,
        (20, 20, 20),
        1.0,
        (1.0, 0.0),
        (96, 200, 500, 225),
        595,
        842,
    )


def _text_item(ref: str, text: str, bbox: tuple[float, float, float, float], page: int = 1) -> dict:
    return {
        "self_ref": ref,
        "label": "text",
        "text": text,
        "prov": [
            {
                "page_no": page,
                "bbox": {
                    "l": bbox[0],
                    "t": bbox[1],
                    "r": bbox[2],
                    "b": bbox[3],
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
    }


def test_watermark_exclusion_does_not_swallow_a_real_paragraph_that_merely_contains_the_same_word(tmp_path):
    """Reproduces a real false-positive class: a large "DRAFT" stamp is a
    genuine watermark and should be excluded, but a normal paragraph that
    happens to use the word "draft" in its own prose ("...reviews the draft
    recommendations...") sitting near it on the page is real content, not
    decoration. The old matching rule treated any paragraph that merely
    *contained* the watermark's short span as text a substring match,
    combined with only a bbox-overlap check — a legitimate paragraph
    positioned anywhere near a large diagonal/stamped watermark satisfies
    both and gets silently deleted from the accessible output."""
    import fitz

    from app.visual_structure import annotate_pdf_artifacts

    path = tmp_path / "watermark.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((80, 450), "DRAFT", fontsize=120)
        page.insert_text(
            (85, 400),
            "The committee reviews the draft recommendations submitted by stakeholders.",
            fontsize=9,
        )
        pdf.save(path)

    document = {
        "texts": [
            _text_item("#/texts/0", "DRAFT", (80.0, 321.0, 479.96, 485.88)),
            _text_item(
                "#/texts/1",
                "The committee reviews the draft recommendations submitted by stakeholders.",
                (85.0, 390.33, 396.62, 402.69),
            ),
        ],
        "pages": {"1": {"size": {"width": 595, "height": 842}}},
    }

    warnings = annotate_pdf_artifacts(document, path)
    assert not warnings

    watermark_item, paragraph_item = document["texts"]
    assert watermark_item.get("meta", {}).get("konverter_exclude_from_output") is True
    assert "meta" not in paragraph_item or not paragraph_item["meta"].get(
        "konverter_exclude_from_output"
    )


def test_repeated_short_answers_on_one_page_are_not_treated_as_a_watermark(tmp_path):
    """A checklist/table with the same short answer repeated several times
    on a single page ("Not applicable" appearing 3+ times) is completely
    ordinary real content, not a running header/footer or watermark — those
    repeat across *many pages* at a consistent position, not merely several
    times within one page's own table or list. The old rule flagged any
    text seen 3+ times on the same page (length <= 60) with no such
    positional/cross-page requirement at all."""
    import fitz

    from app.visual_structure import annotate_pdf_artifacts

    path = tmp_path / "checklist.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        for index in range(3):
            page.insert_text((80, 100 + index * 30), "Not applicable", fontsize=11)
        pdf.save(path)

    document = {
        "texts": [
            _text_item(f"#/texts/{index}", "Not applicable", (80.0, 90.0 + index * 30, 200.0, 105.0 + index * 30))
            for index in range(3)
        ],
        "pages": {"1": {"size": {"width": 595, "height": 842}}},
    }

    warnings = annotate_pdf_artifacts(document, path)
    assert not warnings
    assert all(
        not item.get("meta", {}).get("konverter_exclude_from_output")
        for item in document["texts"]
    )


def test_running_header_repeated_at_same_top_position_across_pages_is_still_excluded(tmp_path):
    """The positive case for the fix above: a genuine running header
    ("Confidential Draft") printed at the same top-margin position on every
    page of a real multi-page document must still be recognised and
    excluded — only same-page repetition and position-inconsistent
    cross-page repetition should be let through as real content."""
    import fitz

    from app.visual_structure import annotate_pdf_artifacts

    path = tmp_path / "running-header.pdf"
    with fitz.open() as pdf:
        for index in range(4):
            page = pdf.new_page(width=595, height=842)
            page.insert_text((80, 40), "Confidential Draft", fontsize=10)
            page.insert_text((80, 200), f"Body paragraph {index} with real content.", fontsize=10)
        pdf.save(path)

    document = {
        "texts": [
            _text_item(f"#/header-{index}", "Confidential Draft", (80.0, 30.0, 220.0, 45.0), page=index + 1)
            for index in range(4)
        ]
        + [
            _text_item(
                f"#/body-{index}",
                f"Body paragraph {index} with real content.",
                (80.0, 190.0, 400.0, 205.0),
                page=index + 1,
            )
            for index in range(4)
        ],
        "pages": {str(index + 1): {"size": {"width": 595, "height": 842}} for index in range(4)},
    }

    warnings = annotate_pdf_artifacts(document, path)
    assert not warnings
    headers = document["texts"][:4]
    bodies = document["texts"][4:]
    assert all(item.get("meta", {}).get("konverter_exclude_from_output") for item in headers)
    assert all(not item.get("meta", {}).get("konverter_exclude_from_output") for item in bodies)


def test_quote_detection_handles_ruled_indented_and_speech_bubble_panels(tmp_path):
    import fitz
    from app.visual_structure import detect_quote_regions

    path = tmp_path / 'quote-layouts.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.draw_line((80, 90), (515, 90))
        page.insert_text((115, 115), 'There are many obstacles that people experience.', fontname='heit', fontsize=11)
        page.insert_text((115, 132), 'We want the opportunity to contribute to our community.', fontname='heit', fontsize=11)
        page.insert_text((340, 151), '—Vision Australia', fontname='helv', fontsize=10)
        page.draw_line((80, 163), (515, 163))
        page.insert_text((80, 200), 'Ordinary body text stays outside the quotation.', fontsize=11)

        page = pdf.new_page(width=595, height=842)
        page.insert_text((80, 100), 'As Justices Maxwell and Charles stated:', fontsize=11)
        page.insert_text((105, 130), 'The court has jurisdiction to decide between competing claims.', fontsize=10)
        page.insert_text((105, 146), 'The decision should be made without unnecessary delay.', fontsize=10)
        page.insert_text((80, 180), 'The following paragraph is not part of that quotation.', fontsize=11)
        page.insert_text((80, 230), 'The participant said:', fontsize=11)
        page.insert_text((80, 260), '1.', fontsize=11)
        page.insert_text((105, 260), 'This is a numbered list item, not quoted speech.', fontsize=11)
        page.insert_text((80, 276), '2.', fontsize=11)
        page.insert_text((105, 276), 'This second list item must also remain a list.', fontsize=11)

        page = pdf.new_page(width=595, height=842)
        page.draw_line((80, 90), (515, 90))
        page.insert_text((110, 120), 'Many people need more support to recover from their experiences.', fontsize=10)
        page.insert_text((110, 136), 'The cost of therapy can prevent people from receiving help.', fontsize=10)
        shape = page.new_shape()
        shape.draw_polyline([(80, 165), (120, 165), (105, 188), (145, 165), (515, 165)])
        shape.finish(color=(0, 0, 0)); shape.commit()
        page.insert_text((340, 196), 'Dr Example', fontsize=10)
        pdf.save(path)

    regions, warnings = detect_quote_regions(path)
    assert not warnings
    assert [(r['page'], r['kind']) for r in regions] == [(1, 'ruled'), (2, 'indented'), (3, 'speech-bubble')]
    assert 'Ordinary body' not in regions[0]['text']
    assert 'following paragraph' not in regions[1]['text']
    assert 'numbered list' not in regions[1]['text']
    assert regions[2]['attribution'] == 'Dr Example'


def test_plain_ruled_body_panel_and_table_are_not_quotes(tmp_path):
    import fitz
    from app.visual_structure import detect_quote_regions
    path = tmp_path / 'not-quotes.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.draw_line((80, 90), (515, 90))
        page.insert_text((100, 120), 'Ordinary information inside a panel is not necessarily a quotation.', fontsize=11)
        page.draw_line((80, 150), (515, 150))
        page.draw_rect((80, 220, 515, 300))
        page.insert_text((100, 240), 'Column heading', fontname='heit', fontsize=11)
        page.insert_text((100, 260), 'Table data that must retain its original structure.', fontsize=11)
        pdf.save(path)
    assert detect_quote_regions(path) == ([], [])


def test_quote_split_preserves_surrounding_prose_and_is_idempotent():
    text = 'Introduction. A quoted statement with meaningful source text. Following paragraph.'
    blocks = [{'id': 'merged', 'label': 'text', 'page': 1, 'order': 0, 'text': text,
               'source_bounds': source_bounds(100, 210)}]
    region = {'page': 1, **source_bounds(135, 170), 'text': 'A quoted statement with meaningful source text.'}
    result = group_quote_blocks(blocks, [region])
    assert [b['label'] for b in result] == ['text', 'quote', 'text']
    assert ' '.join(b['text'] for b in result) == text
    assert group_quote_blocks(result, [region]) == result


def test_quote_does_not_swallow_headings_tables_or_footnotes():
    region = {'page': 1, **source_bounds(100, 220)}
    blocks = [{'id': label, 'label': label, 'text': 'Keep the original structure.', 'page': 1,
               'order': index, 'source_bounds': source_bounds(130, 150)}
              for index, label in enumerate(['section_header_1', 'table', 'footnote'])]
    assert group_quote_blocks(blocks, [region]) == blocks


def test_indented_quote_can_start_on_page_after_attribution(tmp_path):
    import fitz
    from app.visual_structure import detect_quote_regions
    path = tmp_path / 'page-break.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((80, 720), 'The participant told the Commission:', fontsize=11)
        page = pdf.new_page(width=595, height=842)
        page.insert_text((105, 80), 'We needed time and support to find an appropriate outcome.', fontsize=10)
        page.insert_text((105, 96), 'The process placed a significant burden on the family.', fontsize=10)
        page.insert_text((80, 130), 'The next paragraph resumes the report.', fontsize=11)
        pdf.save(path)
    regions, warnings = detect_quote_regions(path)
    assert not warnings
    assert len(regions) == 1 and regions[0]['page'] == 2
    assert 'significant burden' in regions[0]['text']
    assert 'next paragraph' not in regions[0]['text']
