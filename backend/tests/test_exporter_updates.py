from __future__ import annotations

import re

from app.exporter import _render_block, build_accessible_html, build_publication


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


def test_accessible_html_matches_restored_preview_without_site_shell(tmp_path):
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Example report", "order": 0},
            {
                "id": "chapter",
                "label": "section_header_1",
                "text": "1. Introduction",
                "order": 1,
            },
            {
                "id": "purpose",
                "label": "section_header_2",
                "text": "Purpose",
                "order": 2,
            },
            {
                "id": "body",
                "label": "text",
                "text": "This report explains the publication workflow.",
                "order": 3,
            },
            {
                "id": "detail",
                "label": "section_header_3",
                "text": "Detailed scope",
                "order": 4,
            },
            {
                "id": "detail-body",
                "label": "text",
                "text": "A lower-level topic that belongs in the chapter reader only.",
                "order": 5,
            },
            {
                "id": "glossary",
                "label": "section_header_1",
                "text": "Glossary",
                "order": 6,
            },
            {
                "id": "glossary-body",
                "label": "text",
                "text": "Defined terms used in this report.",
                "order": 7,
            },
            {
                "id": "recommendations",
                "label": "section_header_1",
                "text": "Recommendations",
                "order": 8,
            },
            {
                "id": "recommendation-list",
                "label": "list",
                "text": "1. Publish the accessible version.",
                "list_entries": [
                    {
                        "text": "Publish the accessible version.",
                        "marker": "1.",
                        "enumerated": True,
                        "level": 0,
                    }
                ],
                "order": 9,
            },
        ],
        {"title": "Example report", "pages": 3, "file_name": "example.pdf"},
    )
    publication["sections"][0]["blocks"].append(
        {
            "type": "paragraph",
            "id": "footnote-example",
            "text": "The disposal may occur in any manner. 1",
        }
    )
    publication["sections"][0]["footnotes"] = [
        {"id": "footnote-1", "text": "Supporting reference.", "page": 1}
    ]

    rendered = build_accessible_html(
        "document-1",
        publication,
        {
            "title": "Example report",
            "published_date": "2026-06-18",
            "jurisdiction": "Victoria, Australia",
        },
        {"@context": "https://schema.org", "@type": "Report"},
        tmp_path / "cover.png",
        tmp_path / "logo.png",
    )

    # The publishing website supplies the global masthead and footer.
    assert "vlrc-masthead" not in rendered
    assert "vlrc-site-footer" not in rendered
    assert "<header" not in rendered
    assert "<footer" not in rendered
    assert '<script type="application/ld+json">' in rendered
    assert rendered.count("<script") == 1
    assert "<script>" not in rendered
    assert "onclick=" not in rendered

    # The downloadable page uses the restored reviewer-preview design.
    assert 'class="report-card preview-report-card"' in rendered
    assert 'class="report-card-title"' in rendered
    assert 'class="report-card-meta"' in rendered
    assert 'class="report-search"' not in rendered
    assert "Search this report" not in rendered
    assert 'class="key-recommendations"' in rendered
    assert 'class="preview-citation-card"' in rendered
    assert 'class="vlrc-reader"' in rendered
    assert 'class="vlrc-reader-nav"' in rendered
    assert 'class="reader-pagination"' in rendered
    assert 'class="button button-secondary" href="/project/example-report/"' in rendered
    assert ">Go to Project</a>" in rendered

    # The embed fills the width provided by the host template.
    assert "width:100%;max-width:none;background:#fff" in rendered
    assert ".vlrc-publication-embed .vlrc-preview-body{width:100%" in rendered

    # Chapters are collapsible, with H2 headings on the landing page. H3 remains
    # available in the full "In this section" list.
    assert 'class="vlrc-contents"' in rendered
    assert 'class="vlrc-accordion"' in rendered
    assert '<details class="vlrc-accordion-item">' in rendered
    assert '<details class="vlrc-accordion-item" open>' not in rendered
    assert '<summary aria-controls="1-introduction-subsections">' in rendered
    assert 'class="vlrc-accordion-panel"' in rendered
    assert '.vlrc-accordion-item[open]>.vlrc-accordion-panel{display:block;max-height:none;overflow:visible' in rendered
    assert ">Read full section</label>" in rendered
    assert 'href="#purpose"' in rendered
    landing_contents = rendered.split('id="report-contents"', 1)[1].split(
        'class="preview-citation-card"', 1
    )[0]
    assert "Purpose" in landing_contents
    assert "Detailed scope" not in landing_contents
    assert 'class="heading-level-3"' in rendered
    assert ">Detailed scope</a>" in rendered
    assert 'class="vlrc-direct-item"' in rendered
    assert 'for="vlrc-view-0-1-introduction"' in rendered
    assert 'href="/api/documents/document-1/source"' in rendered
    assert "June 18, 2026" in rendered
    assert 'class="vlrc-publication-readers"' in rendered
    assert 'id="vlrc-view-landing" checked' in rendered
    assert '#vlrc-view-0-1-introduction:checked~.vlrc-publication-views #reader-1-introduction{display:block}' in rendered
    assert '.vlrc-publication-views .vlrc-reader{display:none}' in rendered
    assert ":has(" not in rendered
    assert '<sup class="footnote-reference"><a href="#footnote-1" role="doc-noteref" aria-label="Footnote 1">1</a></sup>' in rendered
    assert '<details class="reader-footnotes">' in rendered
    assert '<details class="reader-footnotes" open>' not in rendered
    assert 'type="search"' not in rendered
    assert "data-expand-all" not in rendered
    assert "data-search-result" not in rendered

    # WordPress may remove every script element. The publication interactions
    # remain available through native details, radio view controls and links.
    wordpress_sanitized = re.sub(
        r"<script\b[^>]*>.*?</script>", "", rendered, flags=re.IGNORECASE | re.DOTALL
    )
    assert "<script" not in wordpress_sanitized
    assert '<details class="vlrc-accordion-item">' in wordpress_sanitized
    assert '<details class="vlrc-accordion-item" open>' not in wordpress_sanitized
    assert 'href="#purpose"' in wordpress_sanitized
    assert 'id="purpose"' in wordpress_sanitized
    assert 'for="vlrc-view-0-1-introduction"' in wordpress_sanitized
    assert 'type="radio" name="vlrc-publication-view"' in wordpress_sanitized
    assert 'href="#report-contents"' in wordpress_sanitized
    assert '<sup class="footnote-reference"><a href="#footnote-1"' in wordpress_sanitized


def test_chat_widget_is_baked_in_only_when_a_public_api_url_is_configured(tmp_path):
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Example report", "order": 0},
            {
                "id": "chapter",
                "label": "section_header_1",
                "text": "1. Introduction",
                "order": 1,
            },
            {
                "id": "body",
                "label": "text",
                "text": "This report explains the publication workflow.",
                "order": 2,
            },
        ],
        {"title": "Example report", "pages": 1, "file_name": "example.pdf"},
    )
    metadata = {"title": "Example report"}
    json_ld = {"@context": "https://schema.org", "@type": "Report"}

    without_widget = build_accessible_html(
        "document-1",
        publication,
        metadata,
        json_ld,
        tmp_path / "cover.png",
        tmp_path / "logo.png",
    )
    assert "__KONVERTER_CHAT__" not in without_widget
    assert "konverter-chat-widget.js" not in without_widget

    with_widget = build_accessible_html(
        "document-1",
        publication,
        metadata,
        json_ld,
        tmp_path / "cover.png",
        tmp_path / "logo.png",
        chat_api_base="https://backend.example.com/",
    )
    assert '"documentId": "document-1"' in with_widget
    assert '"apiBase": "https://backend.example.com/api"' in with_widget
    assert (
        '<script src="https://backend.example.com/static/widget/konverter-chat-widget.js" defer>'
        in with_widget
    )


def test_project_button_accepts_a_safe_explicit_url_and_rejects_unsafe_urls(tmp_path):
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Named project: Consultation Paper", "order": 0},
            {"id": "chapter", "label": "section_header_1", "text": "1. Introduction", "order": 1},
        ],
        {"title": "Named project: Consultation Paper", "pages": 1, "file_name": "paper.pdf"},
    )
    arguments = (
        "document-2",
        publication,
        {"@context": "https://schema.org", "@type": "Report"},
        tmp_path / "cover.png",
        tmp_path / "logo.png",
    )

    configured = build_accessible_html(
        arguments[0],
        arguments[1],
        {"title": "Named project: Consultation Paper", "project_url": "https://example.test/project/custom/"},
        arguments[2],
        arguments[3],
        arguments[4],
    )
    unsafe = build_accessible_html(
        arguments[0],
        arguments[1],
        {"title": "Named project: Consultation Paper", "project_url": "javascript:alert(1)"},
        arguments[2],
        arguments[3],
        arguments[4],
    )

    assert 'class="button button-secondary" href="https://example.test/project/custom/"' in configured
    assert 'class="button button-secondary" href="/project/named-project/"' in unsafe
    assert "javascript:alert" not in unsafe


def test_recommendations_box_inside_unrelated_chapter_is_detected(tmp_path):
    # A "Key recommendations" callout box commonly lives inside a chapter
    # titled something else entirely (e.g. "Findings"), not its own chapter
    # literally titled "Recommendations".
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Example report", "order": 0},
            {
                "id": "chapter",
                "label": "section_header_1",
                "text": "1. Findings",
                "order": 1,
            },
            {
                "id": "box",
                "label": "box_section",
                "text": "Publish the accessible version as the primary format.",
                "box_section_title": "Recommendations",
                "box_section_kind": "recommendations",
                "box_section_blocks": [
                    {
                        "label": "text",
                        "text": "Publish the accessible version as the primary format.",
                    }
                ],
                "order": 2,
            },
        ],
        {"title": "Example report", "pages": 1, "file_name": "example.pdf"},
    )

    rendered = build_accessible_html(
        "document-1",
        publication,
        {"title": "Example report"},
        {"@context": "https://schema.org", "@type": "Report"},
        tmp_path / "cover.png",
        tmp_path / "logo.png",
    )

    assert 'class="key-recommendations"' in rendered
    assert "Publish the accessible version as the primary format." in rendered


def test_cite_this_report_ignores_in_document_legal_citations(tmp_path):
    publication = build_publication(
        [
            {"id": "title", "label": "title", "text": "Example report", "order": 0},
            {
                "id": "chapter",
                "label": "section_header_1",
                "text": "1. Introduction",
                "order": 1,
            },
        ],
        {"title": "Example report", "pages": 1, "file_name": "example.pdf"},
    )

    rendered = build_accessible_html(
        "document-1",
        publication,
        {
            "title": "Example report",
            "publisher": "Victorian Law Reform Commission",
            "published_date": "18/06/2026",
            # metadata.citations holds legal citations found in the document
            # body (ISBNs, Acts, case names), not a citation for the report.
            "citations": "ISBN 978-0-6484911-2-3; Smith v Jones [2020] VSC 1",
        },
        {"@context": "https://schema.org", "@type": "Report"},
        tmp_path / "cover.png",
        tmp_path / "logo.png",
    )

    citation_card = rendered.split('class="preview-citation-card"', 1)[1]
    assert "ISBN" not in citation_card
    assert "Smith v Jones" not in citation_card
    assert (
        "Victorian Law Reform Commission, Example report (Report, 2026)"
        in citation_card
    )
