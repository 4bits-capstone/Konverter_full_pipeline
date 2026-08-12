from __future__ import annotations

from app.exporter import build_publication
from app.visual_structure import _span_is_artifact, group_visual_callouts


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
