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


def test_visual_panel_becomes_one_semantic_recommendations_callout():
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

    assert [block["id"] for block in grouped] == ["before", "callout:heading"]
    callout = grouped[1]
    assert callout["callout_title"] == "RECOMMENDATIONS"
    assert callout["callout_kind"] == "recommendations"
    assert callout["callout_blocks"][0]["list_entries"][0]["marker"] == "1."


def test_callout_reaches_preview_publication_as_labelled_aside_content():
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
                "label": "chapter_title",
                "text": "1. Findings",
                "page": 2,
                "order": 1,
            },
            {
                "id": "callout",
                "label": "callout",
                "text": "First recommendation",
                "callout_title": "Recommendations",
                "callout_kind": "recommendations",
                "callout_blocks": [
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
                    }
                ],
                "page": 2,
                "order": 2,
            },
        ],
        {"title": "Example report", "pages": 2, "file_name": "example.pdf"},
    )

    callout = publication["sections"][0]["blocks"][0]
    assert callout["type"] == "callout"
    assert callout["variant"] == "recommendations"
    assert callout["blocks"][0]["type"] == "list"
    assert callout["blocks"][0]["style"] == "ordered"
    assert callout["blocks"][0]["start"] == 4


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
