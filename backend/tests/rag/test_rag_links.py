from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.rag.chunking import chunk_document
from app.rag.links import extract_links
from app.rag.models import Chunk, load_manifest

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = load_manifest(FIXTURES / "documents.json")


def chunk(doc_type: str, section_id: str, text: str, doc_id: str | None = None) -> Chunk:
    doc_id = doc_id or doc_type
    return Chunk(
        chunk_id=section_id, doc_id=doc_id, doc_type=doc_type, section_id=section_id,
        heading_path=["h"], text=text, page_start=1, page_end=1, source_file="x.pdf",
    )


def kinds(links):
    return {(l.from_section, l.to_section, l.kind) for l in links}


def test_report_paragraph_links_to_the_recommendation_it_cites():
    c = chunk("report", "report:para-6.25", "As the Commission recommends (see Recommendations 2 and 3), the agent comes first.")
    found = kinds(extract_links([c], {"report:rec-2", "report:rec-3", "report:para-6.25"}))
    assert found == {("report:para-6.25", "report:rec-2", "refers_to"), ("report:para-6.25", "report:rec-3", "refers_to")}


def test_real_act_text_links_to_acts_own_sections_but_not_other_statutes():
    chunks = chunk_document(MANIFEST["act@038"], json.loads((FIXTURES / "act_front.json").read_text())).chunks
    known = {f"act:s-{n}" for n in ("4", "35", "39", "40", "40A", "84A", "84C")} | {c.section_id for c in chunks}
    found = {(f, t) for f, t, _ in kinds(extract_links(chunks, known))}
    assert ("act:s-3", "act:s-40A") in found and ("act:s-3", "act:s-84C") in found
    assert ("act:s-3", "act:s-35") not in found      # "section 35(2) of the Relationships Act"
    assert ("act:s-4", "act:s-4") not in found
    assert ("act:s-4", "act:s-4") not in found and not any(t == "act:s-4" for f, t in found if f == "act:s-4")


def test_unknown_targets_are_dropped():
    c = chunk("act", "act:s-1", "See section 999 and section 2.", doc_id="act")
    assert kinds(extract_links([c], {"act:s-1", "act:s-2"})) == {("act:s-1", "act:s-2", "refers_to")}


def test_other_statutes_are_not_linked():
    c = chunk("act", "act:s-1", "Despite section 2 of the Wills Act 1997, section 3 of this Act and section 4 apply.")
    assert kinds(extract_links([c], {"act:s-1", "act:s-2", "act:s-3", "act:s-4"})) == {
        ("act:s-1", "act:s-3", "refers_to"),
        ("act:s-1", "act:s-4", "refers_to"),
    }


def test_report_section_refs_need_the_corpus_act_to_be_named():
    named = chunk("report", "report:rec-9", "Section 77 of the Cemeteries and Crematoria Act 2003 (Vic) should be amended.")
    other = chunk("report", "report:rec-10", "Section 6 of the Wills Act 1997 (Vic) and section 77 apply.")
    bare = chunk("report", "report:rec-11", "As required by section 5(1)(b) of the Victorian Law Reform Commission Act 2000.")
    known = {"act:s-77", "act:s-5", "report:rec-9", "report:rec-10", "report:rec-11"}
    found = kinds(extract_links([named, other, bare], known))
    assert found == {("report:rec-9", "act:s-77", "amends")}


def test_recommendation_that_amends_a_section_is_marked_amends():
    c = chunk("report", "report:rec-22", "Recommendation 7 amends section 40 of the Cemeteries and Crematoria Act.")
    found = kinds(extract_links([c], {"report:rec-7", "act:s-40", "report:rec-22"}))
    assert ("report:rec-22", "report:rec-7", "refers_to") in found
    assert ("report:rec-22", "act:s-40", "amends") in found


def test_report_question_refs_only_count_when_they_point_at_the_consultation_paper():
    survey = chunk("report", "report:h-appendix-c", "Question 1 How did you find the process? Question 2 Was it timely?")
    pointer = chunk("report", "report:para-5.3", "The Consultation Paper asked in Questions 3 and 4 whether the law should change.")
    known = {"paper:q-1", "paper:q-2", "paper:q-3", "paper:q-4"}
    assert kinds(extract_links([survey, pointer], known)) == {
        ("report:para-5.3", "paper:q-3", "responds_to"),
        ("report:para-5.3", "paper:q-4", "responds_to"),
    }


def test_paper_questions_that_cite_other_questions():
    c = chunk("paper", "paper:q-10", "Do you have an alternative (other than Questions 3, 4, 6 and 8)?")
    known = {"paper:q-3", "paper:q-4", "paper:q-6", "paper:q-8", "paper:q-10"}
    assert {t for _, t, _ in kinds(extract_links([c], known))} == {f"paper:q-{n}" for n in (3, 4, 6, 8)}


def test_duplicate_mentions_make_one_link():
    c = chunk("act", "act:s-1", "section 2 ... section 2 again", doc_id="act")
    assert len(extract_links([c], {"act:s-1", "act:s-2"})) == 1


# --- legislative history notes cite the AMENDING Act, never this one ---------------------------------

KNOWN = {"act:s-1", "act:s-6A", "act:s-9", "act:s-22", "act:s-40", "act:s-8"}


def test_a_history_note_produces_no_link_to_the_section_it_names():
    text = "6A Cemetery trusts\nS. 6A inserted by No. 61/2009 s. 9.\nThe trust is a body corporate."
    assert kinds(extract_links([chunk("act", "act:s-1", text, doc_id="act")], KNOWN)) == set()


@pytest.mark.parametrize("note", [
    "S. 6A insertedby No. 61/2009 s. 9.",                                   # words run together by the layout
    "S. 6A\ninsertedby\nNo. 61/2009\ns. 9.",                                # wrapped over four lines
    "Sch. 1 cl. 4 (Heading) amendedby No. 61/2009 s. 22(2)(a)",
    "S. 8(1) amended by Nos 61/2009 s. 40, 16/2021 s. 22.",
    "S. 3(1) def.of affected person insertedby | the meaning",                 # fragment: note cut by a table cell
    "inserted by No. 4/2015 ss 8 - 9",
    "by No. 61/2009 s. 9",                                                     # tail only, prefix lost
])
def test_history_note_shapes_never_yield_links(note):
    chunk_ = chunk("act", "act:s-1", f"A holder may inter remains. {note} The trust must keep a register.", doc_id="act")
    assert kinds(extract_links([chunk_], KNOWN)) == set(), note


def test_real_references_next_to_a_history_note_are_still_linked():
    text = "A holder may act under section 8. S. 6A inserted by No. 61/2009 s. 9. See also section 40."
    assert {t for _, t, _ in kinds(extract_links([chunk("act", "act:s-1", text, doc_id="act")], KNOWN))} == {"act:s-8", "act:s-40"}


def test_notes_held_in_metadata_are_not_read_either():
    c = chunk("act", "act:s-1", "A holder may inter remains.", doc_id="act")
    c.metadata = {"history_notes": ["S. 6A inserted by No. 61/2009 s. 9."], "contains": ["act:s-9"]}
    assert extract_links([c], KNOWN) == []


def test_real_act_chunks_with_leftover_note_fragments_do_not_link_to_the_amending_acts_sections():
    for name in ("act_front", "act_end"):
        chunks = chunk_document(MANIFEST["act@038"], json.loads((FIXTURES / f"{name}.json").read_text())).chunks
        known = {f"act:s-{n}" for n in range(1, 200)} | {c.section_id for c in chunks}
        for link in extract_links(chunks, known):
            assert not re.search(r"No\.?s? ?\d+/\d{4}", link.evidence), link
