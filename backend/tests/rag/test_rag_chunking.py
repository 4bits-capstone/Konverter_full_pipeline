from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.rag.chunking import chunk_document
from app.rag.models import Chunk, DocumentInfo, load_manifest

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = load_manifest(FIXTURES / "documents.json")


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def chunks_of(name: str, key: str):
    return chunk_document(MANIFEST[key], load(name))


def by_section(report) -> dict[str, list[Chunk]]:
    out: dict[str, list[Chunk]] = {}
    for chunk in report.chunks:
        out.setdefault(chunk.section_id, []).append(chunk)
    return out


# --- report ------------------------------------------------------------------------------

def test_report_has_all_25_recommendations_including_table_laid_out_ones():
    sections = by_section(chunks_of("report", "report"))
    for n in range(1, 26):
        assert f"report:rec-{n}" in sections, f"recommendation {n} missing"
    # 12-18 arrive from Docling as a 3-column table; they must read like the others.
    rec14 = sections["report:rec-14"][0]
    assert rec14.text.startswith("14 A person’s funeral and burial instructions should only be binding")
    assert "(a) in writing and signed and dated" in rec14.text
    assert rec14.page_start == 21 and rec14.heading_path == ["Recommendations"]


def test_report_recommendation_keeps_its_sub_items_together():
    rec2 = by_section(chunks_of("report", "report"))["report:rec-2"]
    assert len(rec2) == 1
    for marker in ("(a) a funeral and burial agent", "(b) the executor", "(e) any other person"):
        assert marker in rec2[0].text


def test_report_numbered_paragraphs_use_the_converters_number():
    sections = by_section(chunks_of("report", "report"))
    para = sections["report:para-6.25"][0]
    assert para.text.startswith("As discussed in more detail in Chapter 8")
    assert para.heading_path[0].startswith("6.")
    assert para.page_start == para.page_end


def test_recommendation_call_outs_in_a_chapter_do_not_pollute_the_paragraph_above():
    report = chunks_of("report", "report")
    para = by_section(report)["report:para-6.25"][0]
    assert "The Coroners Act 2008 (Vic) should be amended" not in para.text   # that is rec 3's call-out
    assert not para.text.rstrip().endswith("Recommendations")
    assert report.duplicates_dropped >= 1


# --- paper -------------------------------------------------------------------------------

def test_paper_questions_are_recognised_once_each():
    report = chunks_of("paper", "paper")
    sections = by_section(report)
    questions = sorted((s for s in sections if ":q-" in s), key=lambda s: int(s.split("-")[1]))
    assert questions == [f"paper:q-{n}" for n in range(1, 13)]
    # The appendix repeats every question; those copies are dropped, not indexed twice.
    assert report.duplicates_dropped >= 9
    assert not [c for c in report.chunks if "~" in c.chunk_id]


def test_paper_question_keeps_sub_questions_and_drops_trailing_footnotes():
    q4 = by_section(chunks_of("paper", "paper"))["paper:q-4"][0]
    assert "(f) any other factors?" in q4.text
    assert "Ibid" not in q4.text
    q12 = by_section(chunks_of("paper", "paper"))["paper:q-12"][0]
    assert "Published by the Victorian Law Reform Commission" not in q12.text  # appendix end matter


# --- act ---------------------------------------------------------------------------------

def test_act_sections_77_and_79_with_part_and_division_path():
    sections = by_section(chunks_of("act_part6", "act@038"))
    s77 = sections["act:s-77"][0]
    assert s77.chunk_id == "act@038:s-77"
    assert s77.heading_path == [
        "Cemeteries and Crematoria Act 2003",
        "Part 6 — Rights of interment in a public cemetery",
        "Division 1 — Rights of interment generally",
    ]
    assert s77.text.startswith("77 Entitlements of right of interment")
    s79 = sections["act:s-79"][0]
    assert s79.heading_path[-1] == "Division 2 — Transfer and surrender"
    assert "(2) If a person is the sole holder" in s79.text and "transfer" in s79.text


def test_act_page_furniture_and_history_notes_are_not_law_text():
    s77 = by_section(chunks_of("act_part6", "act@038"))["act:s-77"][0]
    assert "No. 80 of 2003" not in s77.text
    assert "Part 6 — Rights" not in s77.text            # the running header repeating the Part
    assert "substitutedby" not in s77.text
    assert s77.metadata["history_notes"] == ["S. 78(2) substitutedby No. 16/2021 s. 10"]


def test_act_table_of_provisions_is_not_chunked():
    report = chunks_of("act_front", "act@038")
    ids = [c.section_id for c in report.chunks]
    assert ids[0] == "act:s-1"
    # (a genuine table inside s 3 is content and stays; the Table of Provisions is not)
    assert not [c for c in report.chunks if "TABLE OF PROVISIONS" in c.text or "Authorised Version No" in c.text]
    assert not [c for c in report.chunks if re.match(r"Section\s*\|\s*Page", c.text)]
    assert len(ids) == len(set(c.chunk_id for c in report.chunks))


def test_act_long_definitions_section_is_split_at_clause_boundaries():
    parts = by_section(chunks_of("act_front", "act@038"))["act:s-3"]
    assert len(parts) >= 3
    assert [c.chunk_id for c in parts][:2] == ["act@038:s-3", "act@038:s-3#2"]
    for part in parts:
        assert len(part.text) <= 2500
        assert part.heading_path[-1] == "Part 1 — Preliminary"
        assert part.embed_text.startswith("Cemeteries and Crematoria Act 2003 > Part 1")


def test_act_section_typed_as_paragraph_schedules_and_endnotes():
    report = chunks_of("act_end", "act@038")
    ids = [c.section_id for c in report.chunks]
    assert "act:s-186" in ids                          # Docling typed this heading as a paragraph
    assert "act:sch1-1" in ids and "act:sch1-2" in ids
    assert not [c for c in report.chunks if "Endnotes" in c.text]
    assert any("181, 182, 183, 184, 185" in w for w in report.warnings)


# --- all documents -------------------------------------------------------------------------

ALL = [
    ("act_front", "act@038"),
    ("act_part6", "act@038"),
    ("act_end", "act@038"),
    ("report", "report"),
    ("paper", "paper"),
]


@pytest.mark.parametrize("name,key", ALL)
def test_every_chunk_carries_the_required_metadata(name: str, key: str):
    info = MANIFEST[key]
    report = chunks_of(name, key)
    assert report.chunks
    assert len({c.chunk_id for c in report.chunks}) == len(report.chunks)
    for c in report.chunks:
        assert c.chunk_id and c.doc_id == info.doc_id and c.doc_type == info.doc_type
        assert c.section_id.startswith(f"{info.doc_id}:")
        assert c.heading_path and all(c.heading_path)
        assert c.version == info.version
        assert c.effective_from == info.effective_from_date and c.effective_from
        assert c.effective_to is None
        assert isinstance(c.page_start, int) and isinstance(c.page_end, int) and c.page_start <= c.page_end
        assert c.source_file == Path(info.file).name
        assert re.fullmatch(r"[0-9a-f]{64}", c.content_hash)
        assert c.text.strip()
        assert c.chunk_id.startswith(f"{info.doc_id}@{info.version}:" if info.version else f"{info.doc_id}:")


def test_effective_dates_follow_the_document_kind():
    assert MANIFEST["act@038"].effective_from_date == "2025-10-22"   # version "as at" date
    assert MANIFEST["report"].effective_from_date == "2016-09-01"    # a report cannot predate itself
    assert MANIFEST["paper"].effective_from_date == "2015-10-08"     # law stated as at


def test_content_hash_covers_text_and_heading_path_only():
    a = chunks_of("report", "report").chunks[1]
    b = Chunk(**{**a.__dict__, "page_start": 99, "metadata": {"x": 1}})
    assert a.content_hash == b.content_hash
    assert a.content_hash != Chunk(**{**a.__dict__, "text": a.text + " changed"}).content_hash
    assert a.content_hash != Chunk(**{**a.__dict__, "heading_path": ["Elsewhere"]}).content_hash
    assert chunks_of("report", "report").chunks[1].content_hash == a.content_hash   # deterministic


def _synthetic_act(sections: list[tuple[str, list[str]]]) -> dict:
    blocks = [{"type": "heading", "level": 3, "text": "Part 1 — Preliminary", "page": 1}]
    for heading, paragraphs in sections:
        blocks.append({"type": "heading", "level": 5, "text": heading, "page": 1})
        blocks += [{"type": "paragraph", "text": p, "page": 1, "number": None} for p in paragraphs]
    return {"publication": {"sections": [{"id": "document-body", "title": "Document", "page": 1, "blocks": blocks}]}}


def test_long_section_is_cut_only_at_subsection_boundaries_and_keeps_heading_path():
    sentence = "The cemetery trust must keep the register accurate and available for inspection. "
    subsections = [f"({i}) " + sentence * 8 for i in range(1, 9)]   # ~650 chars each
    info = DocumentInfo(doc_id="act", doc_type="act", title="Test Act 2000", version="001", published="2024-01-01")
    report = chunk_document(info, _synthetic_act([("1 Register", subsections)]), max_chars=2000)
    parts = report.chunks
    assert len(parts) > 1
    assert [p.chunk_id for p in parts] == ["act@001:s-1"] + [f"act@001:s-1#{i}" for i in range(2, len(parts) + 1)]
    for part in parts:
        assert len(part.text) <= 2000
        assert part.heading_path == ["Test Act 2000", "Part 1 — Preliminary"]
    for part in parts[1:]:
        assert re.match(r"\(\d+\) ", part.text)        # never starts mid-subsection
    assert "".join(re.sub(r"\s", "", p.text) for p in parts).count("(8)") == 1


def test_a_single_oversized_sentence_is_still_bounded():
    info = DocumentInfo(doc_id="act", doc_type="act", title="Test Act 2000", published="2024-01-01")
    blob = ("word " * 1200).strip()
    report = chunk_document(info, _synthetic_act([("1 Huge", [f"(1) {blob}"])]), max_chars=1000)
    assert len(report.chunks) > 1 and all(len(c.text) <= 1000 for c in report.chunks)


def test_manifest_requires_a_known_doc_type():
    with pytest.raises(ValueError):
        DocumentInfo(doc_id="x", doc_type="memo")
