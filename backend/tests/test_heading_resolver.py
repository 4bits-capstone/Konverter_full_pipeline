from __future__ import annotations

from app.config import load_settings
from app.metadata_rules import extract_metadata_from_docling
from app.pipeline import HeadingResolver, KonverterPipeline


def item(
    reference: str,
    label: str,
    text: str,
    page: int,
    *,
    children: list[str] | None = None,
) -> dict:
    value = {
        "self_ref": reference,
        "label": label,
        "text": text,
        "prov": [{"page_no": page}],
    }
    if children is not None:
        value["children"] = [{"$ref": child} for child in children]
    return value


def positioned_item(
    reference: str,
    label: str,
    text: str,
    page: int,
    bbox: tuple[float, float, float, float],
    *,
    heading_level: int | None = None,
    font_size: float | None = None,
) -> dict:
    value = item(reference, label, text, page)
    value["prov"][0]["bbox"] = {
        "l": bbox[0],
        "t": bbox[1],
        "r": bbox[2],
        "b": bbox[3],
    }
    if heading_level is not None or font_size is not None:
        value["meta"] = {
            "konverter_original_label": label,
            "hf__heading_level": heading_level,
            "hf__heading_font_size": font_size,
        }
    return value


def test_chapter_opening_page_drives_h2_when_docling_has_no_title_labels():
    items = {
        "#/texts/0": item("#/texts/0", "section_header", "Example report", 1),
        "#/texts/1": item("#/texts/1", "section_header", "Current law", 10),
        "#/groups/0": item(
            "#/groups/0",
            "list",
            "",
            10,
            children=["#/texts/2", "#/texts/3"],
        ),
        "#/texts/2": item("#/texts/2", "list_item", "6 Introduction", 10),
        "#/texts/3": item("#/texts/3", "list_item", "6 Common law", 10),
        "#/texts/4": item("#/texts/4", "section_header", "2. Current law", 11),
        "#/texts/5": item("#/texts/5", "section_header", "Introduction", 11),
        "#/texts/6": item("#/texts/6", "section_header", "Common law", 11),
        "#/texts/7": item("#/texts/7", "section_header", "Australia", 11),
    }
    order = [
        "#/texts/0",
        "#/texts/1",
        "#/groups/0",
        "#/texts/4",
        "#/texts/5",
        "#/texts/6",
        "#/texts/7",
    ]
    resolver = HeadingResolver("#/texts/0", items, order)

    assert resolver.label_for(items["#/texts/1"]) == "chapter_title"
    assert resolver.is_chapter_contents("#/groups/0")
    assert resolver.label_for(items["#/texts/4"]) == "section_header_1"
    assert resolver.label_for(items["#/texts/5"]) == "section_header_2"
    assert resolver.label_for(items["#/texts/6"]) == "section_header_2"
    assert resolver.label_for(items["#/texts/7"]) == "section_header_3"


def test_split_page_number_and_heading_on_chapter_page_still_becomes_h2():
    items = {
        "#/texts/0": item("#/texts/0", "section_header", "Example report", 1),
        "#/texts/1": item("#/texts/1", "section_header", "Mediation", 20),
        "#/groups/0": item(
            "#/groups/0",
            "key_value_area",
            "",
            20,
            children=["#/texts/2", "#/texts/3", "#/texts/4"],
        ),
        "#/texts/2": item("#/texts/2", "text", "110 Introduction", 20),
        "#/texts/3": item("#/texts/3", "text", "111", 20),
        "#/texts/4": item("#/texts/4", "text", "Responses", 20),
        "#/texts/5": item("#/texts/5", "section_header", "9. Mediation", 21),
        "#/texts/6": item("#/texts/6", "section_header", "Introduction", 21),
        "#/texts/7": item("#/texts/7", "section_header", "Responses", 22),
        "#/texts/8": item("#/texts/8", "section_header", "Effectiveness", 22),
    }
    order = [
        "#/texts/0",
        "#/texts/1",
        "#/groups/0",
        "#/texts/5",
        "#/texts/6",
        "#/texts/7",
        "#/texts/8",
    ]
    resolver = HeadingResolver("#/texts/0", items, order)

    assert resolver.label_for(items["#/texts/1"]) == "chapter_title"
    assert resolver.is_chapter_contents("#/groups/0")
    assert resolver.is_chapter_contents("#/texts/2")
    assert resolver.is_chapter_contents("#/texts/3")
    assert resolver.is_chapter_contents("#/texts/4")
    assert resolver.label_for(items["#/texts/5"]) == "section_header_1"
    assert resolver.label_for(items["#/texts/6"]) == "section_header_2"
    assert resolver.label_for(items["#/texts/7"]) == "section_header_2"
    assert resolver.label_for(items["#/texts/8"]) == "section_header_3"


def test_hierarchical_postprocessor_levels_are_rebased_inside_a_chapter():
    items = {
        "#/texts/0": item("#/texts/0", "title", "Example report", 1),
        "#/texts/1": item("#/texts/1", "title", "Current law", 10),
        "#/texts/2": item("#/texts/2", "section_header", "2. Current law", 11),
        "#/texts/3": item("#/texts/3", "section_header", "Scope", 11),
        "#/texts/4": item("#/texts/4", "section_header", "Exceptions", 12),
    }
    items["#/texts/2"]["meta"] = {"hf__heading_level": 2}
    items["#/texts/3"]["meta"] = {"hf__heading_level": 3}
    items["#/texts/4"]["meta"] = {"hf__heading_level": 4}
    order = list(items)
    resolver = HeadingResolver("#/texts/0", items, order)

    assert resolver.label_for(items["#/texts/1"]) == "chapter_title"
    assert resolver.label_for(items["#/texts/2"]) == "section_header_1"
    assert resolver.label_for(items["#/texts/3"]) == "section_header_2"
    assert resolver.label_for(items["#/texts/4"]) == "section_header_3"


def test_split_chapter_number_and_subtitle_form_one_chapter_heading():
    items = {
        "#/texts/0": item("#/texts/0", "title", "Example report", 1),
        "#/texts/1": item("#/texts/1", "section_header", "Chapter 2", 19),
        "#/texts/2": item(
            "#/texts/2",
            "section_header",
            "Residential Tenancies in Victoria",
            19,
        ),
        "#/texts/3": item("#/texts/3", "section_header", "Private rental market", 19),
    }
    resolver = HeadingResolver("#/texts/0", items, list(items))

    assert resolver.label_for(items["#/texts/1"]) == "chapter_title"
    assert (
        resolver.label_for(items["#/texts/2"])
        == "chapter_title_continuation"
    )
    assert resolver.label_for(items["#/texts/3"]) == "section_header_2"


def test_illustrated_chapter_opener_drives_chapter_h1_and_h2_fallbacks():
    """Regression for Review of the Bail Act pages 23-25 (PDF pages 25-27)."""
    items = {
        "#/texts/0": item("#/texts/0", "title", "Review of the Bail Act", 1),
        # Illustrated opener: Docling may return every fragment as plain text.
        "#/texts/1": item("#/texts/1", "text", "Chapter 2", 25),
        "#/texts/2": item("#/texts/2", "text", "New Bail Act", 25),
        "#/texts/3": item("#/texts/3", "section_header", "CONTENTS", 25),
        "#/texts/4": item("#/texts/4", "text", "24 Accessibility", 25),
        "#/texts/5": item("#/texts/5", "text", "25 Language", 25),
        "#/texts/6": item(
            "#/texts/6", "text", "25 Presentation and Structure", 25
        ),
        "#/texts/7": item(
            "#/texts/7", "text", "28 Deleting Redundant Terms", 25
        ),
        "#/texts/8": item("#/texts/8", "text", "or Provisions", 25),
        # The first body page repeats the split chapter heading.
        "#/texts/9": item("#/texts/9", "text", "Chapter 2", 26),
        "#/texts/10": item("#/texts/10", "text", "New Bail Act", 26),
        # H2 was visually clear but missed by Docling's heading classifier.
        "#/texts/11": item("#/texts/11", "text", "Accessibility", 26),
        "#/texts/12": item("#/texts/12", "section_header", "Language", 27),
        "#/texts/13": item(
            "#/texts/13", "section_header", "Presentation and Structure", 27
        ),
        "#/texts/14": item(
            "#/texts/14", "section_header", "Deleting Redundant Terms or Provisions", 28
        ),
        # Later running headings are page furniture, not repeated H1s.
        "#/texts/15": item("#/texts/15", "text", "Chapter 2", 28),
        "#/texts/16": item("#/texts/16", "text", "New Bail Act", 28),
    }
    order = list(items)
    resolver = HeadingResolver("#/texts/0", items, order)

    assert resolver.label_for(items["#/texts/1"]) == "chapter_title"
    assert resolver.label_for(items["#/texts/2"]) == "chapter_title_continuation"
    assert resolver.is_chapter_contents("#/texts/3")
    assert resolver.is_chapter_contents("#/texts/4")
    assert resolver.is_chapter_contents("#/texts/8")
    assert resolver.is_chapter_context("#/texts/9")
    assert resolver.label_for(items["#/texts/10"]) == "section_header_1"
    assert resolver.label_for(items["#/texts/11"]) == "section_header_2"
    assert resolver.label_for(items["#/texts/12"]) == "section_header_2"
    assert resolver.label_for(items["#/texts/13"]) == "section_header_2"
    assert resolver.label_for(items["#/texts/14"]) == "section_header_2"
    assert resolver.is_chapter_context("#/texts/15")
    assert resolver.is_chapter_context("#/texts/16")


def test_bail_act_chapter_fragments_merge_and_contents_are_not_output():
    text_items = [
        item("#/texts/0", "title", "Review of the Bail Act", 1),
        item("#/texts/1", "text", "Chapter 2", 25),
        item("#/texts/2", "text", "New Bail Act", 25),
        item("#/texts/3", "text", "CONTENTS", 25),
        item("#/texts/4", "text", "24 Accessibility", 25),
        item("#/texts/5", "text", "25 Language", 25),
        item("#/texts/6", "text", "Chapter 2", 26),
        item("#/texts/7", "text", "New Bail Act", 26),
        item("#/texts/8", "text", "Accessibility", 26),
        item("#/texts/9", "section_header", "Language", 27),
    ]
    document = {
        "name": "Review_of_the_Bail_Act_Report_Web",
        "texts": text_items,
        "body": {
            "children": [{"$ref": value["self_ref"]} for value in text_items]
        },
    }

    blocks = KonverterPipeline(load_settings())._blocks_from_document(document, {})

    assert [(block["label"], block["text"]) for block in blocks] == [
        ("title", "Review of the Bail Act"),
        ("chapter_title", "Chapter 2: New Bail Act"),
        ("section_header_1", "New Bail Act"),
        ("section_header_2", "Accessibility"),
        ("section_header_2", "Language"),
    ]


def test_runtime_bail_act_shape_restores_chapter_h1_h2_and_citations():
    """Regression for the supplied 228-page Docling runtime artifacts."""
    text_items = [
        item("#/texts/0", "title", "Review of the Bail Act", 1),
        item(
            "#/texts/1",
            "section_header",
            "Chapter 2 2\r\nNew Bail Act",
            25,
        ),
        item("#/texts/2", "section_header", "CONTENTS", 25),
        item("#/texts/3", "section_header", "24 Accessibility", 25),
        item("#/texts/4", "section_header", "25 Language", 25),
        item("#/texts/5", "section_header", "Chapter 2 2", 26),
        item("#/texts/6", "section_header", "New Bail Act", 26),
        item("#/texts/7", "section_header", "Accessibility", 26),
        item("#/texts/8", "section_header", "Language", 27),
        item("#/texts/9", "section_header", "2 Submission 9.", 27),
    ]
    text_items[1]["meta"] = {
        "konverter_original_label": "section_header",
        "hf__heading_level": 2,
        "hf__heading_font_size": 21.67,
        "konverter_exclude_from_output": True,
    }
    text_items[2]["meta"] = {
        "konverter_original_label": "section_header",
        "hf__heading_level": 3,
        "hf__heading_font_size": 10.37,
    }
    for value in text_items[3:5]:
        value["meta"] = {
            "konverter_original_label": "list_item",
            "hf__heading_level": 3,
            "hf__heading_font_size": 8.52,
        }
    for value in text_items[5:9]:
        value["meta"] = {
            "konverter_original_label": "section_header",
            "hf__heading_level": 3,
            "hf__heading_font_size": 8.89,
        }
    text_items[9]["meta"] = {
        "konverter_original_label": "list_item",
        "hf__heading_level": 4,
        "hf__heading_font_size": 5.40,
    }
    document = {
        "name": "Review_of_the_Bail_Act_Report_Web",
        "texts": text_items,
        # Deliberately scrambled hierarchy parents must not alter source order.
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/5"},
                {"$ref": "#/texts/1"},
            ]
        },
    }

    blocks = KonverterPipeline(load_settings())._blocks_from_document(document, {})
    structures = [(block["label"], block["text"]) for block in blocks]

    assert ("chapter_title", "Chapter 2: New Bail Act") in structures
    assert ("section_header_1", "New Bail Act") in structures
    assert ("section_header_2", "Accessibility") in structures
    assert ("section_header_2", "Language") in structures
    assert not any(text == "CONTENTS" for _, text in structures)
    assert ("list", "2 Submission 9.") in structures
    assert all(
        blocks[index]["page"] <= blocks[index + 1]["page"]
        for index in range(len(blocks) - 1)
    )


def test_rule_based_headings_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("KONVERTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KONVERTER_RULE_BASED_HEADINGS", "false")
    settings = load_settings()
    document = {
        "name": "Package only",
        "texts": [
            {
                **item("#/texts/0", "title", "Document title", 1),
                "level": 1,
                "meta": {"hf__heading_level": 1},
            },
            {
                **item("#/texts/1", "section_header", "Package section", 2),
                "level": 2,
                "meta": {"hf__heading_level": 2},
            },
            {
                **item("#/texts/2", "section_header", "Direct child", 2),
                "level": 3,
                "meta": {"hf__heading_level": 3},
            },
            {
                **item("#/texts/3", "section_header", "Nested child", 2),
                "level": 4,
                "meta": {"hf__heading_level": 4},
            },
        ],
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/1"},
                {"$ref": "#/texts/2"},
                {"$ref": "#/texts/3"},
            ]
        },
    }

    blocks = KonverterPipeline(settings)._blocks_from_document(document, {})

    assert settings.rule_based_headings is False
    assert any(
        block["label"] == "chapter_title"
        and block["text"] == "Package section"
        for block in blocks
    )
    assert any(
        block["label"] == "section_header_1"
        and block["text"] == "Direct child"
        for block in blocks
    )
    assert any(
        block["label"] == "section_header_2"
        and block["text"] == "Nested child"
        for block in blocks
    )


def test_layout_chapter_uses_body_h1_instead_of_decorative_ocr():
    text_items = [
        positioned_item(
            "#/texts/0",
            "title",
            "Example report",
            1,
            (80, 700, 360, 650),
            heading_level=1,
            font_size=24,
        ),
        positioned_item(
            "#/texts/1",
            "text",
            "THE REPORT THE REPORT THE REPORT " * 20,
            10,
            (0, 680, 420, 150),
        ),
        positioned_item(
            "#/texts/2",
            "section_header",
            "CONTENTS",
            10,
            (440, 580, 500, 568),
            heading_level=5,
            font_size=10,
        ),
        positioned_item(
            "#/texts/3",
            "list_item",
            "11 Community Attitudes Data",
            10,
            (452, 560, 560, 550),
        ),
        positioned_item(
            "#/texts/4",
            "section_header",
            "Chapter 4 4",
            11,
            (70, 740, 160, 715),
            heading_level=5,
            font_size=23,
        ),
        positioned_item(
            "#/texts/5",
            "section_header",
            "Surveys of Attitudes",
            11,
            (185, 740, 380, 718),
            heading_level=5,
            font_size=21,
        ),
        positioned_item(
            "#/texts/6",
            "section_header",
            "Community Attitudes Data",
            11,
            (185, 680, 340, 670),
            heading_level=4,
            font_size=9,
        ),
        positioned_item(
            "#/texts/7",
            "section_header",
            "1. General Description",
            11,
            (185, 640, 320, 630),
            heading_level=5,
            font_size=8,
        ),
    ]
    document = {
        "name": "Example",
        "texts": text_items,
        "pages": {
            str(page): {
                "page_no": page,
                "size": {"width": 595.276, "height": 841.89},
            }
            for page in (1, 10, 11)
        },
        "body": {
            "children": [{"$ref": value["self_ref"]} for value in text_items]
        },
    }

    blocks = KonverterPipeline(load_settings())._blocks_from_document(document, {})
    structures = [(block["label"], block["text"]) for block in blocks]

    assert ("chapter_title", "Chapter 4: Surveys of Attitudes") in structures
    assert ("section_header_1", "Surveys of Attitudes") in structures
    assert ("section_header_2", "Community Attitudes Data") in structures
    assert not any(text == "CONTENTS" for _, text in structures)
    assert not any(
        label == "chapter_title" and text == "1. General Description"
        for label, text in structures
    )
    assert not any("THE REPORT THE REPORT" in text for _, text in structures)


def test_merged_contents_text_promotes_each_matching_body_heading():
    text_items = [
        positioned_item(
            "#/texts/0",
            "title",
            "Example report",
            1,
            (80, 700, 360, 650),
            heading_level=1,
            font_size=24,
        ),
        positioned_item(
            "#/texts/1",
            "section_header",
            "Chapter 2 2 Assistance Animals 2 in Victoria",
            17,
            (58, 605, 295, 528),
            heading_level=2,
            font_size=23,
        ),
        positioned_item(
            "#/texts/2",
            "section_header",
            "CONTENTS",
            17,
            (439, 577, 497, 567),
            heading_level=3,
            font_size=10,
        ),
        positioned_item(
            "#/texts/3",
            "text",
            "Who uses assistance animals? What benefits do assistance animals bring?",
            17,
            (452, 550, 568, 515),
        ),
        positioned_item(
            "#/texts/4",
            "section_header",
            "Chapter 2 2",
            18,
            (74, 740, 160, 715),
            heading_level=4,
            font_size=23,
        ),
        positioned_item(
            "#/texts/5",
            "section_header",
            "Assistance Animals in Victoria",
            18,
            (184, 740, 480, 720),
            heading_level=4,
            font_size=19,
        ),
        positioned_item(
            "#/texts/6",
            "section_header",
            "Who uses assistance animals?",
            18,
            (184, 600, 340, 590),
            heading_level=4,
            font_size=9,
        ),
        positioned_item(
            "#/texts/7",
            "section_header",
            "What benefits do assistance animals bring?",
            18,
            (184, 500, 390, 490),
            heading_level=4,
            font_size=9,
        ),
    ]
    document = {
        "name": "Example",
        "texts": text_items,
        "pages": {
            str(page): {
                "page_no": page,
                "size": {"width": 595.276, "height": 841.89},
            }
            for page in (1, 17, 18)
        },
        "body": {
            "children": [{"$ref": value["self_ref"]} for value in text_items]
        },
    }

    blocks = KonverterPipeline(load_settings())._blocks_from_document(document, {})
    h2_text = {
        block["text"] for block in blocks if block["label"] == "section_header_2"
    }

    assert "Who uses assistance animals?" in h2_text
    assert "What benefits do assistance animals bring?" in h2_text


def test_split_chapter_subtitle_uses_layout_when_pdf_stream_order_is_unusual():
    items = {
        "#/texts/0": item("#/texts/0", "title", "Example report", 1),
        "#/texts/1": item("#/texts/1", "text", "Chapter 2", 25),
        # A sidebar can occur first in the PDF content stream.
        "#/texts/2": item(
            "#/texts/2", "text", "Legislation should be", 25
        ),
        "#/texts/3": item("#/texts/3", "text", "New Bail Act", 25),
        "#/texts/4": item("#/texts/4", "text", "CONTENTS", 25),
        "#/texts/5": item("#/texts/5", "text", "26 Drafting", 25),
    }
    items["#/texts/1"]["prov"][0]["bbox"] = {
        "l": 80,
        "t": 720,
        "r": 170,
        "b": 690,
    }
    items["#/texts/2"]["prov"][0]["bbox"] = {
        "l": 30,
        "t": 400,
        "r": 170,
        "b": 380,
    }
    items["#/texts/3"]["prov"][0]["bbox"] = {
        "l": 180,
        "t": 720,
        "r": 330,
        "b": 680,
    }
    resolver = HeadingResolver("#/texts/0", items, list(items))

    assert resolver.label_for(items["#/texts/1"]) == "chapter_title"
    assert resolver.label_for(items["#/texts/3"]) == "chapter_title_continuation"
    assert resolver.label_for(items["#/texts/2"]) == "text"


def test_confidence_matching_uses_only_clusters_from_the_same_page():
    document = {
        "pages": {
            "1": {"size": {"height": 100}},
            "2": {"size": {"height": 100}},
        },
        "texts": [
            {
                "self_ref": "#/texts/0",
                "prov": [
                    {
                        "page_no": 2,
                        "bbox": {"l": 10, "t": 10, "r": 30, "b": 30},
                    }
                ],
            }
        ],
    }
    clusters = [
        (1, {"l": 10, "t": 10, "r": 30, "b": 30}, 0.1),
        (2, {"l": 10, "t": 10, "r": 30, "b": 30}, 0.9),
    ]

    confidence = KonverterPipeline._confidence_by_reference(document, clusters)

    assert confidence["#/texts/0"] == 0.9


def test_multi_column_list_is_linearised_by_column_then_vertical_position():
    document = {
        "pages": {"1": {"size": {"width": 600, "height": 800}}},
    }

    def list_item(reference: str, text: str, left: int, top: int) -> dict:
        return {
            "self_ref": reference,
            "label": "list_item",
            "text": text,
            "prov": [
                {
                    "page_no": 1,
                    "bbox": {"l": left, "t": top, "r": left + 210, "b": top + 20},
                }
            ],
        }

    items = [
        list_item("right-1", "Right one", 330, 100),
        list_item("left-1", "Left one", 70, 90),
        list_item("right-2", "Right two", 330, 150),
        list_item("left-2", "Left two", 70, 140),
    ]

    ordered = KonverterPipeline._ordered_list_items(document, items)

    assert [value["text"] for value in ordered] == [
        "Left one",
        "Left two",
        "Right one",
        "Right two",
    ]


def test_rule_metadata_uses_existing_docling_text(monkeypatch, tmp_path):
    monkeypatch.setenv("KONVERTER_DATA_DIR", str(tmp_path))
    document = {
        "texts": [
            item("#/texts/0", "title", "Example Accessibility Report", 1),
            item("#/texts/1", "text", "Report June 2026", 1),
            item(
                "#/texts/2",
                "text",
                "Published by the Victorian Law Reform Commission "
                "The Victorian Law Reform Commission was established by law.",
                2,
            ),
            item(
                "#/texts/3",
                "text",
                "Victorian Law Reform Commission Act 2000 (Vic)",
                2,
            ),
        ],
    }

    payload = extract_metadata_from_docling(
        document,
        tmp_path / "example.pdf",
        load_settings(),
    )

    assert payload["metadata"] == {
        "title": "Example Accessibility",
        "publisher": "Victorian Law Reform Commission",
        "published_date": "2026-06",
        "jurisdiction": "Victoria, Australia",
        "citations": "Victorian Law Reform Commission Act 2000 (Vic)",
    }
    assert payload["fields"]["publisher"]["source"].startswith("Docling text · page 2")


def test_cataloguing_title_stops_before_merged_publication_details(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("KONVERTER_DATA_DIR", str(tmp_path))
    document = {
        "texts": [
            item(
                "#/texts/0",
                "text",
                "Committals: Report / Victorian Law Reform Commission "
                "ISBN 978-0-9943725-6-7 Series: Report "
                "(Victorian Law Reform Commission) 41 Ordered to be published "
                "Victorian Government Printer PP 122, Session 2018–20 "
                "Alison O'Brien PSM Gemma Varley PSM",
                2,
            ),
        ],
    }

    payload = extract_metadata_from_docling(
        document,
        tmp_path / "committals-report.pdf",
        load_settings(),
    )

    assert payload["metadata"]["title"] == "Committals"
    assert payload["fields"]["title"]["score"] == 0.98
    assert "ISBN" not in payload["metadata"]["title"]


def test_bail_act_cataloguing_style_beats_decorative_cover_fragments(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("KONVERTER_DATA_DIR", str(tmp_path))
    document = {
        "texts": [
            item(
                "#/texts/0",
                "text",
                "www.lawreform.vic.gov.au REVIEW OF THE BAIL ACT",
                1,
            ),
            item("#/texts/1", "text", "Final Report VIEW OF", 1),
            item("#/texts/2", "text", "E BAIL ACT", 1),
            item(
                "#/texts/3",
                "text",
                "Review of the Bail Act : Final Report.",
                2,
            ),
            item("#/texts/4", "text", "©August 2007 Victorian Law Reform Commission.", 2),
        ]
    }

    payload = extract_metadata_from_docling(
        document,
        tmp_path / "Review_of_the_Bail_Act_Report_Web.pdf",
        load_settings(),
    )

    assert payload["metadata"]["title"] == "Review of the Bail Act"
    assert payload["metadata"]["published_date"] == "2007-08"


def test_residential_cataloguing_style_is_title_cased(monkeypatch, tmp_path):
    monkeypatch.setenv("KONVERTER_DATA_DIR", str(tmp_path))
    document = {
        "texts": [
            item(
                "#/texts/0",
                "section_header",
                "Residential Tenancy Databases Report",
                1,
            ),
            item(
                "#/texts/1",
                "text",
                "National Library of Australia Residential tenancy databases: report.",
                2,
            ),
            item("#/texts/2", "text", "© March 2006 Victorian Law Reform Commission.", 2),
        ]
    }

    payload = extract_metadata_from_docling(
        document,
        tmp_path / "ResidentialTenancyDatabases_FinalReport.pdf",
        load_settings(),
    )

    assert payload["metadata"]["title"] == "Residential Tenancy Databases"
    assert payload["metadata"]["published_date"] == "2006-03"


def test_docling_device_can_be_configured_for_cuda(monkeypatch, tmp_path):
    monkeypatch.setenv("KONVERTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KONVERTER_DOCLING_DEVICE", "cuda")

    assert load_settings().docling_device == "cuda"


def test_review_queue_uses_configured_confidence_thresholds(monkeypatch, tmp_path):
    monkeypatch.setenv("KONVERTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KONVERTER_HIGH_CONFIDENCE", "0.80")
    monkeypatch.setenv("KONVERTER_MEDIUM_CONFIDENCE", "0.60")
    pipeline = KonverterPipeline(load_settings())
    blocks = [
        {"id": "high", "label": "text", "text": "High", "page": 1, "confidence": 0.80},
        {
            "id": "medium",
            "label": "text",
            "text": "Medium",
            "page": 1,
            "confidence": 0.79,
        },
        {"id": "low", "label": "text", "text": "Low", "page": 1, "confidence": 0.59},
    ]

    review_items = pipeline._build_review_items(blocks)

    assert [item["block_id"] for item in review_items] == ["medium", "low"]
    assert [item["band"] for item in review_items] == ["med", "low"]
