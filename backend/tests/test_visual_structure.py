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
