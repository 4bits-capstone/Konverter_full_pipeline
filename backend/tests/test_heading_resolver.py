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
