"""Act sections whose heading the converter lost must not be cited as the section before them."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.rag.chunking import chunk_document
from app.rag.models import load_manifest

FIXTURES = Path(__file__).parent / "fixtures"
ACT = load_manifest(FIXTURES / "documents.json")["act@038"]


def structured(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def pdf_pages(mutate=None) -> list[str]:
    stored = json.loads((FIXTURES / "act_pdf_pages.json").read_text(encoding="utf-8"))["pages"]
    pages = [""] * (max(map(int, stored)))
    for number, text in stored.items():
        pages[int(number) - 1] = mutate(int(number), text) if mutate else text
    return pages


def by_section(chunks):
    out = {}
    for c in chunks:
        out.setdefault(c.section_id, []).append(c)
    return out


# (fixture, previous section, recovered sections, how they are recovered)
CASES = [
    ("act_gap_s5", "act:s-4", ["act:s-5"], None),                              # cut from the converter's own atoms
    ("act_gap_s7", "act:s-6B", ["act:s-7", "act:s-8", "act:s-9"], "pdf-text-layer"),
    ("act_gap_s29", "act:s-28", ["act:s-29"], "pdf-text-layer"),               # converter kept the text but not in order
    ("act_gap_s63", "act:s-62", ["act:s-63"], "pdf-text-layer"),               # converter lost the text altogether
    ("act_gap_s83", "act:s-82", ["act:s-83"], "pdf-text-layer"),
]


@pytest.mark.parametrize("name,previous,recovered,source", CASES)
def test_missing_sections_become_their_own_units(name, previous, recovered, source):
    report = chunk_document(ACT, structured(name), pdf_pages=pdf_pages())
    sections = by_section(report.chunks)
    for section in recovered:
        assert section in sections, f"{section} not recovered"
        number = section.split("-")[1]
        first = sections[section][0]
        assert first.text.startswith(f"{number} ")
        assert first.metadata.get("text_source") == source
        assert "contains" not in first.metadata
        assert first.chunk_id.startswith("act@038:s-")
    # the section before it no longer carries the recovered text
    for chunk in sections[previous]:
        assert "contains" not in chunk.metadata


def test_recovered_text_is_the_real_section_text_not_the_neighbours():
    sections = by_section(chunk_document(ACT, structured("act_gap_s7"), pdf_pages=pdf_pages()).chunks)
    assert sections["act:s-7"][0].text == (
        "7 Cemetery trusts do not represent the Crown\n"
        "A cemetery trust does not represent and is not to be taken to be part of the Crown."
    )
    assert "Management of public cemeteries" in sections["act:s-8"][0].text
    assert "Crown." not in "".join(c.text for c in sections["act:s-6B"])


def test_recovered_sections_from_the_other_cases_read_correctly():
    s29 = by_section(chunk_document(ACT, structured("act_gap_s29"), pdf_pages=pdf_pages()).chunks)["act:s-29"][0]
    assert s29.text.startswith("29 Effect of Division\nThis Division has effect despite anything")
    sections = by_section(chunk_document(ACT, structured("act_gap_s5"), pdf_pages=pdf_pages()).chunks)
    assert sections["act:s-5"][0].text.startswith("5 Establishment of cemetery trusts\n(1) The Governor in Council")
    assert "Establishment of cemetery trusts" not in "".join(c.text for c in sections["act:s-4"])


def test_rebuilt_sections_carry_no_page_furniture():
    report = chunk_document(ACT, structured("act_gap_s83"), pdf_pages=pdf_pages())
    text = "\n".join(c.text for c in report.chunks)
    for junk in ("Authorised by the Chief Parliamentary Counsel", "No. 80 of 2003", "Part 6", "Division 4"):
        assert junk not in text
    assert report.chunks[-1].page_end >= report.chunks[-1].page_start


def test_without_the_pdf_the_previous_chunks_say_which_sections_they_hold():
    report = chunk_document(ACT, structured("act_gap_s5"))      # no PDF text layer available
    sections = by_section(report.chunks)
    assert "act:s-5" not in sections
    for chunk in sections["act:s-4"]:
        assert chunk.metadata["contains"] == ["act:s-4", "act:s-5"]
    assert any("marked as containing" in w for w in report.warnings)


def test_multiple_missing_sections_are_all_listed_when_unrecoverable():
    report = chunk_document(ACT, structured("act_gap_s7"))
    for chunk in by_section(report.chunks)["act:s-6B"]:
        assert chunk.metadata["contains"] == ["act:s-6B", "act:s-7", "act:s-8", "act:s-9"]


def test_when_recovery_truly_fails_the_chunk_carries_contains():
    # The heading of s 29 is in the PDF, but the section before it cannot be located there
    # (its heading is garbled), so neither the cut nor the rebuild can be done safely.
    def garble(page: int, text: str) -> str:
        return text.replace("28 Governor in Council", "28Governor in Council")

    report = chunk_document(ACT, structured("act_gap_s29"), pdf_pages=pdf_pages(garble))
    sections = by_section(report.chunks)
    assert "act:s-29" not in sections
    for chunk in sections["act:s-28"]:
        assert chunk.metadata["contains"] == ["act:s-28", "act:s-29"]
        assert "text_source" not in chunk.metadata
    assert any("could not be separated" in w for w in report.warnings)


def test_repealed_sections_have_no_heading_in_the_pdf_and_are_not_invented():
    report = chunk_document(ACT, structured("act_end"), pdf_pages=pdf_pages())
    ids = {c.section_id for c in report.chunks}
    assert {"act:s-180", "act:s-186"} <= ids
    assert not any(i in ids for i in (f"act:s-{n}" for n in range(181, 186)))
    assert all("contains" not in c.metadata for c in report.chunks)
    assert any("repealed or omitted" in w and "181, 182, 183, 184, 185" in w for w in report.warnings)


def test_margin_notes_split_over_several_lines_are_removed_from_rebuilt_text():
    # In the PDF text layer "S. 6A inserted by No. 61/2009 s. 9." is interleaved with the body and
    # wraps over four lines; one even lands in the middle of a sentence.
    sections = by_section(chunk_document(ACT, structured("act_gap_s7"), pdf_pages=pdf_pages()).chunks)
    six_b = sections["act:s-6B"][0]
    assert "No. 61/2009" not in six_b.text and "S. 6" not in six_b.text
    assert "taken to be a Class B cemetery trust unless this Act or any subsequent order" in six_b.text
    assert "S. 6A insertedby No. 61/2009 s. 9." in " ".join(six_b.metadata["history_notes"])
