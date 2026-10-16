from pathlib import Path

from app.metadata_rules import (
    _payload,
    empty_metadata_payload,
    extract_citations,
    extract_date,
    extract_jurisdiction,
    extract_publisher,
    extract_title,
)
from app.service import _legacy_field_flags, _legacy_field_location

# No such file exists, so PDF-property lookups quietly return nothing.
PDF = Path("missing_report_2016.pdf")


def _pages(*texts: str) -> list[dict]:
    return [{"number": index, "text": text} for index, text in enumerate(texts, start=1)]


def _codes(field: dict) -> list[str]:
    return [item["code"] for item in field["flags"]]


def test_fields_carry_flags_instead_of_confidence_scores():
    payload = empty_metadata_payload()
    for info in payload["fields"].values():
        assert "score" not in info and "band" not in info
        assert info["review_needed"] is True
        assert [flag["code"] for flag in info["flags"]] == ["missing"]


def test_clean_cataloguing_title_needs_no_review():
    field = extract_title(
        _pages("Sentencing Reform : final report / Victorian Law Reform Commission"),
        PDF,
    )
    assert field["value"] == "Sentencing Reform"
    assert field["flags"] == []


def test_close_competing_titles_are_flagged_as_a_rule_conflict():
    field = extract_title(
        _pages("Title: Review of the Bail Act", "Title: Succession Laws"),
        PDF,
    )
    assert "rule_conflict" in _codes(field)
    conflict = next(f for f in field["flags"] if f["code"] == "rule_conflict")
    assert conflict["severity"] == "review"
    assert "page 2" in conflict["message"]


def test_title_falling_back_to_the_file_name_is_flagged():
    field = extract_title(_pages("nothing useful here"), Path("VLRC_Bail_Review_forweb.pdf"))
    assert field["method"] == "filename_fallback"
    assert _codes(field) == ["fallback_source"]


def test_disagreeing_date_rules_are_flagged():
    field = extract_date(
        _pages("Final Report June 2016", "© October 2015 Victorian Law Reform Commission"),
        PDF,
    )
    assert field["value"] == "2016-06"
    assert _codes(field) == ["rule_conflict"]
    assert "2015-10" in field["flags"][0]["message"]


def test_agreeing_date_rules_raise_no_flag():
    field = extract_date(
        _pages("Final Report June 2016", "© Victorian Law Reform Commission 2016"),
        PDF,
    )
    assert field["value"] == "2016-06"
    assert field["flags"] == []


def test_year_only_date_is_flagged_as_partial():
    field = extract_date(_pages("© Victorian Law Reform Commission 2016"), PDF)
    assert field["value"] == "2016"
    assert _codes(field) == ["partial_value"]


def test_two_published_by_lines_naming_different_bodies_conflict():
    field = extract_publisher(
        _pages(
            "Published by the Victorian Law Reform Commission.",
            "Published by Department of Justice.",
        )
    )
    assert field["value"] == "Victorian Law Reform Commission"
    assert _codes(field) == ["rule_conflict"]


def test_parliamentary_tabling_line_is_not_a_competing_publisher():
    field = extract_publisher(
        _pages(
            "Published by the Victorian Law Reform Commission.",
            "Published by order, or under the authority, of the Parliament of Victoria, May 2024",
        )
    )
    assert field["value"] == "Victorian Law Reform Commission"
    assert field["flags"] == []


def test_publisher_inferred_from_a_single_organisation_mention_needs_review():
    field = extract_publisher(_pages("Victorian Law Reform Commission"))
    assert field["flags"][0]["code"] == "inferred"
    assert field["flags"][0]["severity"] == "review"


def test_publisher_inferred_from_repeated_mentions_is_informational():
    field = extract_publisher(
        _pages("Victorian Law Reform Commission", "Victorian Law Reform Commission")
    )
    assert field["flags"][0]["severity"] == "info"


def test_single_jurisdiction_mention_is_flagged():
    field = extract_jurisdiction(_pages("Crimes Act 1958 (Vic)"))
    assert _codes(field) == ["single_match"]


def test_close_rival_jurisdiction_is_a_conflict_but_a_passing_mention_is_not():
    close = extract_jurisdiction(
        _pages("Victoria", "Victoria", "New South Wales")
    )
    assert "rule_conflict" in _codes(close)

    passing = extract_jurisdiction(
        _pages("Victoria", "Victoria", "Victoria", "New South Wales")
    )
    other = next(f for f in passing["flags"] if f["code"] == "other_values")
    assert other["severity"] == "info"


def test_citations_without_an_isbn_or_series_anchor_are_flagged():
    field = extract_citations(_pages("See the Bail Act 1977 (Vic)."))
    assert _codes(field) == ["uncorroborated"]

    anchored = extract_citations(
        _pages("ISBN 978-0-9922-1234-5", "See the Bail Act 1977 (Vic).")
    )
    assert anchored["flags"] == []


def test_legacy_confidence_fields_are_converted_to_flags():
    low = _legacy_field_flags({"band": "med", "score": 0.7, "page": 2})
    assert low["review_needed"] is True
    assert [f["code"] for f in low["flags"]] == ["review_needed"]
    assert "band" not in low and "score" not in low

    high = _legacy_field_flags({"band": "high", "score": 0.95, "page": 1})
    assert high == {"page": 1, "flags": [], "review_needed": False}


def _location(**fields: dict) -> dict[str, str]:
    return {name: info["location"] for name, info in _payload(fields)["fields"].items()}


def test_each_field_says_which_page_and_line_it_came_from():
    pages = _pages(
        "Final Report June 2016",
        "Sentencing Reform : final report / Victorian Law Reform Commission\n"
        "Published by the Victorian Law Reform Commission\n"
        "ISBN 978-0-9876543-2-1",
        "Sentencing Act 1991 (Vic)",
    )
    locations = _location(
        title=extract_title(pages, PDF),
        publisher=extract_publisher(pages, PDF),
        published_date=extract_date(pages, PDF),
        citations=extract_citations(pages),
    )
    assert locations == {
        "title": "Page 2 · cataloguing details",
        "publisher": "Page 2 · “Published by” line",
        "published_date": "Page 1 · report line",
        "citations": "Pages 2, 3",
    }


def test_fallback_and_missing_values_say_where_they_did_not_come_from():
    locations = _location(
        title=extract_title(_pages("nothing useful here"), Path("Bail_Review.pdf")),
        publisher=extract_publisher(_pages("nothing useful here"), PDF),
    )
    assert locations == {
        "title": "File name",
        "publisher": "None found in pages 1–8",
    }


def test_legacy_fields_get_a_page_only_location():
    known = _legacy_field_location({"source": "Docling text · page 3 · cover_date_rule"})
    assert known["location"] == "Page 3"
    unknown = _legacy_field_location({"source": "Docling text · pages 1–8 · not_found"})
    assert unknown["location"] == ""
