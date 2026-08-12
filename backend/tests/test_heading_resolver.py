from __future__ import annotations

from pathlib import Path

import pymupdf

from app.toc_hierarchy import TocHierarchyResolver, extract_toc_outline


def _make_contents_pdf(path: Path) -> None:
    document = pymupdf.open()
    for _ in range(6):
        document.new_page(width=595, height=842)

    document[0].insert_text((72, 90), "Example report", fontsize=24)
    contents = document[1]
    contents.insert_text((72, 70), "Contents", fontsize=20)
    contents.insert_text((72, 115), "Preface ........................ iii", fontsize=11)
    contents.insert_text((72, 140), "1. Introduction ................. 1", fontsize=11)
    contents.insert_text((96, 165), "Background ...................... 2", fontsize=11)
    contents.insert_text((72, 190), "Glossary ........................ 3", fontsize=11)
    # This is ordinary content sharing the TOC page. It must not be removed.
    contents.insert_text((350, 115), "Preface", fontsize=11)

    document[2].insert_text((72, 90), "Preface", fontsize=18)
    document[3].insert_text((72, 90), "1. Introduction", fontsize=18)
    document[3].insert_text(
        (72, 140), "Major body heading", fontsize=14, fontname="hebo"
    )
    document[3].insert_text(
        (72, 180), "Nested body heading", fontsize=12, fontname="hebo"
    )
    document[3].insert_text(
        (72, 220), "Detail body heading", fontsize=11, fontname="hebo"
    )
    document[4].insert_text((72, 90), "Background", fontsize=15)
    document[5].insert_text((72, 90), "Glossary", fontsize=18)
    document.save(path)
    document.close()


def _docling_item(
    reference: str,
    text: str,
    page: int,
    bbox: tuple[float, float, float, float],
    *,
    label: str = "text",
    level: int | None = None,
) -> dict:
    item = {
        "self_ref": reference,
        "label": label,
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
    if level is not None:
        item["level"] = level
    return item


def test_printed_contents_drives_two_level_outline(tmp_path: Path) -> None:
    pdf_path = tmp_path / "contents.pdf"
    _make_contents_pdf(pdf_path)

    outline = extract_toc_outline(pdf_path)

    assert outline.warnings == []
    assert outline.toc_pages == {2}
    assert [(entry.title, entry.level) for entry in outline.entries] == [
        ("Preface", 1),
        ("1. Introduction", 1),
        ("Background", 2),
        ("Glossary", 1),
    ]
    assert all(entry.target_page is not None for entry in outline.entries)


def test_only_contents_regions_are_suppressed_on_mixed_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "mixed.pdf"
    _make_contents_pdf(pdf_path)
    items = [
        _docling_item("#/texts/0", "Example report", 1, (72, 70, 240, 100), label="title"),
        _docling_item("#/texts/1", "Preface ........................ iii", 2, (72, 104, 260, 119)),
        _docling_item("#/texts/2", "Preface", 2, (350, 104, 500, 119)),
        _docling_item("#/texts/3", "1. Introduction", 4, (72, 72, 240, 100), label="section_header", level=1),
        _docling_item("#/texts/4", "Body subsection", 4, (300, 130, 470, 150), label="section_header", level=2),
    ]
    item_map = {item["self_ref"]: item for item in items}
    document = {
        "pages": {
            str(page): {"size": {"width": 595, "height": 842}}
            for page in range(1, 7)
        }
    }
    resolver = TocHierarchyResolver(
        pdf_path,
        document,
        item_map,
        list(item_map),
        "#/texts/0",
    )

    assert resolver.is_toc_item(items[1]) is True
    assert resolver.is_toc_item(items[2]) is False
    assert resolver.label_for(items[3]) == "section_header_1"
    assert resolver.label_for(items[4]) == "section_header_4"

    blocks = [
        {
            "id": item["self_ref"],
            "label": resolver.label_for(item),
            "text": resolver.output_text(item),
            "page": item["prov"][0]["page_no"],
            "source_bounds": {"top": item["prov"][0]["bbox"]["t"]},
        }
        for item in (items[0], items[2], items[3], items[4])
    ]
    output = resolver.apply_outline(blocks)

    assert "#/texts/2" in [block["id"] for block in output]
    headings = [
        (block["label"], block["text"])
        for block in output
        if block["label"].startswith("section_header_")
    ]
    assert ("section_header_1", "Preface") in headings
    assert ("section_header_1", "1. Introduction") in headings
    assert ("section_header_2", "Background") in headings
    assert ("section_header_1", "Glossary") in headings


def test_body_heading_wins_over_same_named_chapter_contents_row(tmp_path: Path) -> None:
    pdf_path = tmp_path / "chapter-row-vs-heading.pdf"
    _make_contents_pdf(pdf_path)
    items = [
        _docling_item(
            "#/texts/local-row",
            "Background",
            4,
            (96, 130, 240, 148),
            label="list_item",
        ),
        _docling_item(
            "#/texts/body-heading",
            "Background",
            5,
            (72, 72, 240, 100),
            label="section_header",
            level=2,
        ),
    ]
    item_map = {item["self_ref"]: item for item in items}
    resolver = TocHierarchyResolver(
        pdf_path,
        {
            "pages": {
                str(page): {"size": {"width": 595, "height": 842}}
                for page in range(1, 7)
            }
        },
        item_map,
        list(item_map),
        None,
    )
    background = next(
        entry for entry in resolver.outline.entries if entry.title == "Background"
    )

    assert background.matched_ref == "#/texts/body-heading"
    assert resolver.label_for(item_map["#/texts/body-heading"]) == "section_header_2"


def test_no_contents_page_returns_explicit_warning(tmp_path: Path) -> None:
    pdf_path = tmp_path / "plain.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 90), "A document without printed contents")
    document.save(pdf_path)
    document.close()

    outline = extract_toc_outline(pdf_path)

    assert outline.entries == []
    assert outline.warnings == [
        "No printed table of contents was detected; checking chapter title pages.",
        "No chapter title pages could be confirmed; the heading hierarchy may be incomplete.",
    ]


def test_chapter_title_pages_repair_flattened_toc_h1_and_local_h2(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "flattened-contents.pdf"
    document = pymupdf.open()
    for _ in range(7):
        document.new_page(width=595, height=842)
    document[0].insert_text((72, 90), "Example report", fontsize=24)
    document[1].insert_text((72, 70), "Contents", fontsize=20)
    document[1].insert_text((72, 115), "Preface ........ i", fontsize=11)
    # The designed main TOC flattens both chapter titles; neither row says
    # Chapter or begins with a number.
    document[1].insert_text((72, 140), "Introduction ........ 1", fontsize=11)
    document[1].insert_text((72, 165), "Background ........ 2", fontsize=11)
    document[1].insert_text((72, 190), "Glossary ........ 3", fontsize=11)
    document[2].insert_text((72, 90), "Preface", fontsize=18)

    first = document[3]
    first.insert_text((72, 90), "Chapter 1", fontsize=22)
    first.insert_text((72, 125), "Introduction", fontsize=28)
    first.insert_text((72, 165), "CONTENTS", fontsize=14)
    first.insert_text((72, 195), "1 Scope of this report", fontsize=10)

    second = document[4]
    second.insert_text((72, 90), "Chapter 2", fontsize=22)
    second.insert_text((72, 125), "Background", fontsize=28)
    second.insert_text((72, 165), "CONTENTS", fontsize=14)
    second.insert_text((72, 195), "2 Previous reviews", fontsize=10)
    document[5].insert_text((72, 90), "Glossary", fontsize=18)
    document.set_page_labels(
        [
            {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
            {"startpage": 3, "prefix": "", "style": "D", "firstpagenum": 1},
        ]
    )
    document.save(pdf_path)
    document.close()

    outline = extract_toc_outline(pdf_path)

    h1 = [entry.title for entry in outline.entries if entry.level == 1]
    assert h1 == ["Preface", "Introduction", "Background", "Glossary"]
    assert any(
        entry.level == 2 and entry.title == "Scope of this report"
        for entry in outline.entries
    )
    assert any(
        entry.level == 2 and entry.title == "Previous reviews"
        for entry in outline.entries
    )


def test_printed_page_labels_win_over_conflicting_duplicate_bookmarks(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "conflicting-bookmarks.pdf"
    document = pymupdf.open()
    for _ in range(7):
        document.new_page(width=595, height=842)
    document[0].insert_text((72, 90), "Example report", fontsize=24)
    document[1].insert_text((72, 70), "Contents", fontsize=20)
    document[1].insert_text((72, 115), "1. Introduction ........ 1", fontsize=11)
    document[1].insert_text((72, 140), "2. Current law .......... 2", fontsize=11)
    document[1].insert_text((72, 165), "3. Conclusion ........... 3", fontsize=11)
    document[2].insert_text((72, 90), "1. Introduction", fontsize=18)
    document[3].insert_text((72, 90), "2. Current law", fontsize=18)
    document[4].insert_text((72, 90), "3. Conclusion", fontsize=18)
    document[5].insert_text((72, 90), "Introduction", fontsize=14)
    document[6].insert_text((72, 90), "Conclusion", fontsize=14)
    document.set_page_labels(
        [
            {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
            {"startpage": 2, "prefix": "", "style": "D", "firstpagenum": 1},
        ]
    )
    document.set_toc(
        [
            [1, "1. Introduction", 6],
            [1, "2. Current law", 4],
            [1, "3. Conclusion", 7],
        ]
    )
    document.save(pdf_path)
    document.close()

    outline = extract_toc_outline(pdf_path)

    assert [entry.title for entry in outline.entries] == [
        "1. Introduction",
        "2. Current law",
        "3. Conclusion",
    ]
    assert [entry.target_page for entry in outline.entries] == [3, 4, 5]


def test_body_typography_resolves_h3_h4_h5(tmp_path: Path) -> None:
    pdf_path = tmp_path / "body-styles.pdf"
    _make_contents_pdf(pdf_path)
    with pymupdf.open(pdf_path) as document:
        page = document[3]
        values = {
            text: tuple(page.search_for(text)[0])
            for text in (
                "1. Introduction",
                "Major body heading",
                "Nested body heading",
                "Detail body heading",
            )
        }
    items = [
        _docling_item("#/texts/0", "Example report", 1, (72, 70, 240, 100), label="title"),
        *[
            _docling_item(
                f"#/texts/{index}",
                text,
                4,
                values[text],
                label="section_header",
                level=5,
            )
            for index, text in enumerate(values, start=1)
        ],
    ]
    item_map = {item["self_ref"]: item for item in items}
    document_payload = {
        "pages": {
            str(page): {"size": {"width": 595, "height": 842}}
            for page in range(1, 7)
        }
    }
    resolver = TocHierarchyResolver(
        pdf_path,
        document_payload,
        item_map,
        list(item_map),
        "#/texts/0",
    )

    assert resolver.label_for(item_map["#/texts/2"]) == "section_header_3"
    assert resolver.label_for(item_map["#/texts/3"]) == "section_header_4"
    assert resolver.label_for(item_map["#/texts/4"]) == "section_header_5"


def test_chapter_contents_list_is_not_repeated_in_reader_body(tmp_path: Path) -> None:
    pdf_path = tmp_path / "chapter-contents.pdf"
    _make_contents_pdf(pdf_path)
    intro = _docling_item(
        "#/texts/intro",
        "1. Introduction",
        4,
        (72, 72, 240, 100),
        label="section_header",
        level=1,
    )
    items = {intro["self_ref"]: intro}
    resolver = TocHierarchyResolver(pdf_path, {"pages": {}}, items, list(items), None)
    output = resolver.apply_outline(
        [
            {
                "id": intro["self_ref"],
                "label": resolver.label_for(intro),
                "text": "1. Introduction",
                "page": 4,
                "source_bounds": {"top": 72},
            },
            {
                "id": "#/texts/contents",
                "label": "section_header_5",
                "text": "CONTENTS",
                "page": 4,
                "source_bounds": {"top": 110},
            },
            {
                "id": "#/groups/chapter-contents",
                "label": "list",
                "text": "2 Background\n3 Scope",
                "page": 4,
                "source_bounds": {"top": 125},
            },
            {
                "id": "#/texts/body",
                "label": "text",
                "text": "Body content remains.",
                "page": 4,
                "source_bounds": {"top": 240},
            },
        ]
    )

    assert "CONTENTS" not in [block["text"] for block in output]
    assert "2 Background\n3 Scope" not in [block["text"] for block in output]
    assert "Body content remains." in [block["text"] for block in output]


def test_untitled_local_chapter_contents_panel_is_not_repeated(tmp_path: Path) -> None:
    pdf_path = tmp_path / "untitled-chapter-contents.pdf"
    document = pymupdf.open()
    for _ in range(6):
        document.new_page(width=595, height=842)
    document[0].insert_text((72, 90), "Example report", fontsize=24)
    document[1].insert_text((72, 70), "Contents", fontsize=20)
    document[1].insert_text((72, 115), "1. Introduction ........ 1", fontsize=11)
    document[1].insert_text((96, 140), "Terms of reference ...... 2", fontsize=11)
    document[1].insert_text((96, 165), "Scope of the reference .. 3", fontsize=11)
    document[2].insert_text((72, 90), "1. Introduction", fontsize=22)
    document[3].insert_text((72, 90), "Terms of reference", fontsize=15)
    document[4].insert_text((72, 90), "Scope of the reference", fontsize=15)
    document.set_page_labels(
        [
            {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
            {"startpage": 2, "prefix": "", "style": "D", "firstpagenum": 1},
        ]
    )
    document.save(pdf_path)
    document.close()

    resolver = TocHierarchyResolver(pdf_path, {"pages": {}}, {}, [], None)
    output = resolver.apply_outline(
        [
            {
                "id": "local-list",
                "label": "list",
                "text": "2 Terms of reference\n3 Scope of the reference",
                "list_entries": [
                    {"text": "2 Terms of reference"},
                    {"text": "3 Scope of the reference"},
                ],
                "page": 3,
                "source_bounds": {"top": 180},
            },
            {
                "id": "body",
                "label": "text",
                "text": "Body content remains.",
                "page": 3,
                "source_bounds": {"top": 300},
            },
        ]
    )

    assert "2 Terms of reference\n3 Scope of the reference" not in [
        block["text"] for block in output
    ]
    assert "Body content remains." in [block["text"] for block in output]
