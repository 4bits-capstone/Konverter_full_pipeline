from __future__ import annotations

from app.exporter import _render_block, build_publication


def test_all_printed_contents_sections_are_kept_before_and_after_chapters():
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Report", "order": 0},
            {"id": "preface", "label": "section_header_1", "text": "Preface", "order": 1},
            {"id": "preface-text", "label": "text", "text": "Preface body", "order": 2},
            {"id": "chapter", "label": "section_header_1", "text": "1. Introduction", "order": 3},
            {"id": "background", "label": "section_header_2", "text": "Background", "order": 4},
            {"id": "glossary", "label": "section_header_1", "text": "Glossary", "order": 5},
        ],
        {"title": "Report", "pages": 4, "file_name": "report.pdf"},
    )

    assert [section["displayTitle"] for section in publication["sections"]] == [
        "Preface",
        "1. Introduction",
        "Glossary",
    ]
    assert [
        heading["text"] for heading in publication["sections"][1]["headings"]
    ] == ["Background"]
    assert [section["isChapter"] for section in publication["sections"]] == [
        False,
        True,
        False,
    ]


def test_printed_toc_sequence_controls_landing_section_order():
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Report", "order": 0},
            {
                "id": "chapter-2",
                "label": "section_header_1",
                "text": "2. Current law",
                "toc_sequence": 2,
                "order": 1,
            },
            {"id": "chapter-2-text", "label": "text", "text": "Second", "order": 2},
            {
                "id": "chapter-1",
                "label": "section_header_1",
                "text": "1. Introduction",
                "toc_sequence": 1,
                "order": 3,
            },
            {"id": "chapter-1-text", "label": "text", "text": "First", "order": 4},
        ],
        {"title": "Report", "pages": 2, "file_name": "report.pdf"},
    )

    assert [section["displayTitle"] for section in publication["sections"]] == [
        "1. Introduction",
        "2. Current law",
    ]


def test_unsequenced_front_and_back_matter_are_placed_by_pdf_page():
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Report", "order": 0},
            {
                "id": "chapter-1",
                "label": "section_header_1",
                "text": "1. Introduction",
                "toc_sequence": 10,
                "page": 10,
                "order": 1,
            },
            {"id": "preface", "label": "section_header_1", "text": "Preface", "page": 2, "order": 2},
            {
                "id": "chapter-2",
                "label": "section_header_1",
                "text": "2. Findings",
                "toc_sequence": 20,
                "page": 20,
                "order": 3,
            },
            {"id": "appendices", "label": "section_header_1", "text": "Appendices", "page": 30, "order": 4},
            {"id": "bibliography", "label": "section_header_1", "text": "Bibliography", "page": 40, "order": 5},
        ],
        {"title": "Report", "pages": 40, "file_name": "report.pdf"},
    )

    assert [section["displayTitle"] for section in publication["sections"]] == [
        "Preface",
        "1. Introduction",
        "2. Findings",
        "Appendices",
        "Bibliography",
    ]


def test_lower_heading_levels_are_closed_up_without_skipping_ranks():
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Report", "order": 0},
            {
                "id": "chapter",
                "label": "section_header_1",
                "text": "1. Introduction",
                "order": 1,
            },
            {
                "id": "major",
                "label": "section_header_2",
                "text": "Major topic",
                "order": 2,
            },
            {
                "id": "detail",
                "label": "section_header_5",
                "text": "Detail promoted to the next valid rank",
                "order": 3,
            },
            {
                "id": "nested",
                "label": "section_header_4",
                "text": "Nested detail",
                "order": 4,
            },
            {
                "id": "deep",
                "label": "section_header_5",
                "text": "Deep detail",
                "order": 5,
            },
        ],
        {"title": "Report", "pages": 2, "file_name": "report.pdf"},
    )

    assert [
        heading["level"] for heading in publication["sections"][0]["headings"]
    ] == [2, 3, 4, 5]


def test_scope_of_report_is_used_before_introduction_for_description():
    blocks = [
        {"id": "title", "label": "title", "text": "Example report", "order": 0},
        {
            "id": "intro",
            "label": "section_header_1",
            "text": "1. Introduction",
            "order": 1,
        },
        {
            "id": "intro-text",
            "label": "text",
            "text": "This introduction provides general background but is not the preferred summary source.",
            "order": 2,
        },
        {
            "id": "scope",
            "label": "section_header_2",
            "text": "1.2 Scope of this report",
            "order": 3,
        },
        {
            "id": "scope-text",
            "label": "text",
            "text": (
                "This report examines how accessible publishing requirements can be "
                "reviewed and applied consistently. It explains which structures must "
                "remain available to readers using assistive technology."
            ),
            "order": 4,
        },
        {
            "id": "next",
            "label": "section_header_2",
            "text": "1.3 Method",
            "order": 5,
        },
        {
            "id": "method-text",
            "label": "text",
            "text": "This sentence belongs to the next section and must not be included.",
            "order": 6,
        },
    ]

    publication = build_publication(
        blocks,
        {"title": "Example report", "pages": 2, "file_name": "example.pdf"},
        summary_max_chars=400,
    )

    description = publication["summary"][0]
    assert description.startswith("This report examines")
    assert "next section" not in description
    assert len(description) <= 400


def test_table_without_source_caption_has_no_generated_caption_heading():
    rendered = _render_block(
        {
            "type": "table",
            "id": "table-1",
            "caption": "",
            "rows": [
                [
                    {
                        "text": "Value",
                        "columnHeader": True,
                        "rowHeader": False,
                    }
                ]
            ],
        }
    )

    assert "Extracted table" not in rendered
    assert "<caption>" not in rendered
    assert 'aria-label="Table; scroll horizontally when needed"' in rendered


def test_ordered_list_preserves_source_start_and_item_numbers():
    rendered = _render_block(
        {
            "type": "list",
            "style": "ordered",
            "start": 4,
            "items": [
                {
                    "text": "Keep the original fourth recommendation.",
                    "marker": "4.",
                    "ordered": True,
                    "value": 4,
                },
                {
                    "text": "Keep a deliberate numbering gap.",
                    "marker": "6.",
                    "ordered": True,
                    "value": 6,
                },
            ],
        }
    )

    assert '<ol class="source-list" start="4">' in rendered
    assert '<li value="4">Keep the original fourth recommendation.</li>' in rendered
    assert '<li value="6">Keep a deliberate numbering gap.</li>' in rendered
    assert "<ul" not in rendered


def test_box_section_uses_semantic_ordered_and_unordered_lists():
    publication = build_publication(
        [
            {
                "id": "title",
                "label": "title",
                "text": "Example report",
                "order": 0,
                "page": 1,
            },
            {
                "id": "chapter",
                "label": "section_header_1",
                "text": "1. Findings",
                "order": 1,
                "page": 2,
            },
            {
                "id": "box",
                "label": "box_section",
                "text": "7. First action\n8. Second action\n• Supporting note",
                "box_section_title": "Recommendations",
                "box_section_kind": "recommendations",
                "box_section_blocks": [
                    {
                        "label": "list",
                        "text": "7. First action\n8. Second action\n• Supporting note",
                        "list_entries": [
                            {
                                "text": "First action",
                                "marker": "7.",
                                "enumerated": True,
                                "level": 0,
                            },
                            {
                                "text": "Second action",
                                "marker": "8.",
                                "enumerated": True,
                                "level": 0,
                            },
                            {
                                "text": "Supporting note",
                                "marker": "•",
                                "enumerated": False,
                                "level": 0,
                            },
                        ],
                        "page": 2,
                    }
                ],
                "order": 2,
                "page": 2,
            },
        ],
        {"title": "Example report", "pages": 2, "file_name": "example.pdf"},
    )

    box = publication["sections"][0]["blocks"][0]
    assert box["type"] == "box_section"
    assert box["blocks"][0]["style"] == "ordered"
    assert box["blocks"][0]["start"] == 7
    assert box["blocks"][0]["items"][0]["value"] == 7
    assert box["blocks"][1]["style"] == "unordered"

    rendered = _render_block(box)
    assert '<ol class="source-list" start="7">' in rendered
    assert '<ul class="source-list">' in rendered
