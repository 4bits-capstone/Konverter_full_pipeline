from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.rag import cli
from app.rag.answer import ranked_sections
from app.rag.ask import ask
from app.rag.embeddings import HashEmbedder
from app.rag.evalrun import load_questions, run_eval, write_results
from app.rag.ingest import Source, ingest
from app.rag.llm import LLMReply
from app.rag.models import DocumentInfo
from app.rag.retrieve import RetrievalOptions, retrieve
from app.rag.settings import RagSettings
from app.rag.store import MemoryStore

ROOT = Path(__file__).resolve().parents[3]
SETTINGS = RagSettings(min_similarity=0.3, top_k=3)


class SpyEmbedder(HashEmbedder):
    def __init__(self):
        super().__init__(16)
        self.input_types = []

    def embed(self, texts, input_type="document"):
        self.input_types.append(input_type)
        return super().embed(texts, input_type)


class FakeLLM:
    model = "deepseek-chat"

    def __init__(self, payload=None):
        self.payload, self.calls, self.messages = payload, 0, None

    def complete(self, messages):
        self.calls += 1
        self.messages = messages
        return LLMReply(json.dumps(self.payload), "deepseek-chat", {"total_tokens": 1})


def act(version, sections, effective_from="2024-01-01", effective_to=None) -> Source:
    """sections: [(number, title, text)] -> a tiny Act."""
    info = DocumentInfo(doc_id="act", doc_type="act", title="Test Act 2000", version=version, published="2024-01-01",
                        effective_from=effective_from, effective_to=effective_to, file=f"act{version}.pdf")
    blocks = [{"type": "heading", "level": 3, "text": "Part 1 — Preliminary", "page": 1}]
    for number, title, text in sections:
        blocks += [{"type": "heading", "level": 5, "text": f"{number} {title}", "page": number},
                   {"type": "paragraph", "text": text, "page": number, "number": None}]
    structured = {"publication": {"sections": [{"id": "document-body", "title": "Document", "page": 1, "blocks": blocks}]}}
    return Source(f"act@{version}", info, structured, "unreviewed")


def build(*sources) -> tuple[MemoryStore, HashEmbedder]:
    store, embedder = MemoryStore(), HashEmbedder(16)
    ingest(sources, embedder, store, SETTINGS)
    return store, embedder


SECTIONS = [
    (1, "Interment", "Inhumation plot burial remains."),
    (2, "Memorials", "Plaque monument headstone allowed. See section 1 and section 3."),
    (3, "Transfer", "Assignment conveyance price."),
    (4, "Fees", "Levy tariff schedule. See section 3."),
    (5, "Records", "Ledger register kept. See section 1."),
    (6, "Offences", "Desecration vandalism offence. See section 2."),
]


def sections_of(rows):
    return [r["section_id"] for r in rows]


# --- links ------------------------------------------------------------------------------------

def test_links_are_off_by_default_and_the_store_is_not_asked():
    store, embedder = build(act("038", SECTIONS))
    calls = []
    store.expand_links = lambda *a, **k: calls.append(1) or []
    rows = retrieve("holder memorial", embedder, store, RetrievalOptions(k=2))
    assert len(rows) == 2 and not calls and not any(r.get("via_link") for r in rows)


def test_the_question_is_embedded_as_a_query():
    store, _ = build(act("038", SECTIONS))
    spy = SpyEmbedder()
    retrieve("holder", spy, store, RetrievalOptions(k=1))
    assert spy.input_types == ["query"]


def test_linked_sections_follow_the_vector_results_one_hop_in_both_directions():
    store, embedder = build(act("038", SECTIONS))
    plain = retrieve("plaque monument headstone", embedder, store, RetrievalOptions(k=1))
    assert sections_of(plain) == ["act:s-2"]
    rows = retrieve("plaque monument headstone", embedder, store, RetrievalOptions(k=1, links=True))
    assert sections_of(rows)[0] == "act:s-2"
    added = {r["section_id"]: r["via_link"] for r in rows[1:]}
    assert set(added) == {"act:s-1", "act:s-3", "act:s-6"}            # s-2 cites 1 and 3; s-6 cites s-2 (incoming)
    assert added["act:s-1"] == {"from": "act:s-2", "kind": "refers_to"} and added["act:s-6"]["from"] == "act:s-2"
    assert all(r["similarity"] is None for r in rows[1:])


def test_expansion_is_one_hop_and_capped_at_three():
    store, embedder = build(act("038", SECTIONS))
    rows = retrieve("levy tariff schedule", embedder, store, RetrievalOptions(k=1, links=True))
    assert sections_of(rows)[:1] == ["act:s-4"] and sections_of(rows)[1:] == ["act:s-3"]       # s-4 -> s-3 only; no second hop
    rows = retrieve("inhumation plot burial", embedder, store, RetrievalOptions(k=1, links=True))
    extra = rows[1:]
    assert len(extra) <= 3 and "act:s-1" not in {r["section_id"] for r in extra}
    wide = retrieve("inhumation", embedder, store, RetrievalOptions(k=1, links=True, link_cap=1))
    assert len([r for r in wide if r.get("via_link")]) <= 1


def test_sections_already_retrieved_are_not_added_again():
    store, embedder = build(act("038", SECTIONS))
    rows = retrieve("inhumation plaque assignment", embedder, store, RetrievalOptions(k=3, links=True))
    ids = [r["chunk_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_expansion_cannot_leak_a_version_that_is_not_in_force():
    old = act("037", SECTIONS[:2] + [(3, "Transfer", "Assignment conveyance at cost.")], "2024-01-01", "2025-10-22")
    new = act("038", SECTIONS[:2] + [(3, "Transfer", "Assignment conveyance capped price.")], "2025-10-22")
    store, embedder = build(old, new)
    for as_of, version in (("2025-01-01", "037"), ("2026-01-01", "038")):
        rows = retrieve("plaque monument headstone", embedder, store,
                        RetrievalOptions(k=1, links=True, as_of_date=as_of))
        assert {r["version"] for r in rows} == {version}, as_of
        assert "act:s-3" in sections_of(rows)
    rows = retrieve("plaque", embedder, store, RetrievalOptions(k=1, links=True))        # no date: newest version of a linked section
    assert [r["version"] for r in rows if r.get("via_link")] == ["038"] * len([r for r in rows if r.get("via_link")])


def test_expansion_respects_the_document_filter_and_metadata_filter():
    other = DocumentInfo(doc_id="other", doc_type="report", title="Other", published="2024-01-01", file="o.pdf")
    structured = {"publication": {"sections": [{"id": "c", "title": "C", "page": 1, "blocks": [
        {"type": "heading", "level": 1, "text": "1. Intro", "page": 1},
        {"type": "paragraph", "text": "Plaque monument headstone discussed. See recommendation 1.", "page": 1, "number": "1.1"}]}]}}
    store, embedder = build(act("038", SECTIONS), Source("other", other, structured, "reviewed"))
    rows = retrieve("plaque monument headstone", embedder, store, RetrievalOptions(k=1, links=True, doc_ids=["act"]))
    assert {r["doc_id"] for r in rows} == {"act"}
    rows = retrieve("plaque monument headstone", embedder, store,
                    RetrievalOptions(k=1, links=True, meta_filter={"review_status": "reviewed"}))
    assert all(r["doc_id"] == "other" for r in rows)


# --- ask ------------------------------------------------------------------------------------------

def test_ask_returns_the_n8n_shaped_result_and_the_rows():
    store, embedder = build(act("038", SECTIONS))
    llm = FakeLLM({"answer": "Plaques are allowed [act:s-2].", "citations": ["act:s-2"], "abstained": False})
    result, rows = ask("plaque monument headstone", embedder, store, llm,
                       RagSettings(min_similarity=0.0), RetrievalOptions(k=2))
    assert result["citations"] == ["act:s-2"] and result["abstained"] is False and result["latency_ms"] >= 0
    assert ranked_sections(result)[0] == "act:s-2" and rows[0]["section_id"] == "act:s-2"
    assert "[act:s-2] (Test Act 2000 | version 038 | Test Act 2000 > Part 1 — Preliminary | p. 2)" in llm.messages[1]["content"]


def test_linked_sections_reach_the_model_even_though_they_have_no_similarity():
    store, embedder = build(act("038", SECTIONS))
    llm = FakeLLM({"answer": "See [act:s-1].", "citations": ["act:s-1"], "abstained": False})
    result, _ = ask("plaque monument headstone", embedder, store, llm,
                    RagSettings(min_similarity=0.99), RetrievalOptions(k=1, links=True))
    assert result["abstained"] is False and result["citations"] == ["act:s-1"]
    assert any(s.get("via_link") and s["similarity"] is None for s in result["scores"])
    assert "[act:s-1]" in llm.messages[1]["content"]


def test_nothing_ingested_is_not_found_and_the_model_is_not_called():
    llm = FakeLLM({})
    result, rows = ask("anything", HashEmbedder(16), MemoryStore(), llm, SETTINGS)
    assert rows == [] and result["abstained"] and result["abstain_reason"] == "no_passages" and llm.calls == 0


# --- eval -----------------------------------------------------------------------------------------

def load_score():
    spec = importlib.util.spec_from_file_location("score", ROOT / "eval" / "score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eval_lines_are_what_score_py_reads(tmp_path):
    store, embedder = build(act("038", SECTIONS))
    questions = [
        {"id": "Q1", "category": "single", "question": "plaque monument headstone", "gold_sections": "act:s-2"},
        {"id": "Q2", "category": "unanswerable", "question": "zzzz qqqq", "gold_sections": ""},
    ]
    llm = FakeLLM({"answer": "x [act:s-2]", "citations": ["act:s-2"], "abstained": False})
    rows = list(run_eval(questions, embedder, store, llm, RagSettings(min_similarity=0.5), RetrievalOptions(k=3), "vector"))
    out = tmp_path / "results.jsonl"
    assert write_results(rows, out) == 2
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert {"question_id", "setup", "retrieved", "answer", "abstained", "latency_ms"} <= set(lines[0])
    assert lines[0]["retrieved"][0] == "act:s-2" and lines[0]["setup"] == "vector"
    assert lines[0]["model"] == "deepseek-chat"                                  # so runs on different models are never mixed up
    assert lines[1]["retrieved"] and lines[1]["used"] == [] and lines[1]["abstained"] is True      # ranked before the floor, none passed it
    assert lines[1]["top_similarity"] is not None
    score = load_score()
    summary = score.summarise({q["id"]: {**q, "gold": [g for g in q["gold_sections"].split(";") if g]} for q in questions}, lines)
    assert summary["vector"]["single"]["recall"] == 1.0 and summary["vector"]["unanswerable"]["abstain"] == 1.0


def test_the_real_questions_file_loads_and_q12_is_marked_footnote_dependent():
    questions = load_questions(ROOT / "eval" / "questions.csv")
    assert len(questions) == 16
    q12 = next(q for q in questions if q["id"] == "Q12")
    assert q12["gold_sections"] == "report:para-7.9;act:s-77" and q12["notes"].startswith("footnote-dependent")


# --- cli ------------------------------------------------------------------------------------------

@pytest.fixture
def wired(monkeypatch):
    store, embedder = build(act("038", SECTIONS))
    llm = FakeLLM({"answer": "Plaques are allowed [act:s-2].", "citations": ["act:s-2"], "abstained": False})
    monkeypatch.setattr(cli, "build_embedder", lambda s: embedder)
    monkeypatch.setattr(cli, "SupabaseStore", lambda s: store)
    monkeypatch.setattr(cli, "DeepSeekClient", lambda s: llm)
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.0")
    return store, llm


def test_cli_ask_prints_answer_citations_and_chunks(wired, capsys):
    assert cli.main(["ask", "plaque monument headstone", "--doc", "act", "-k", "2", "--links"]) == 0
    out = capsys.readouterr().out
    assert "Answer: Plaques are allowed [act:s-2]." in out and "Citations: act:s-2" in out
    assert "act@038:s-2" in out and "linked from act:s-2: refers_to" in out and "Retrieved (" in out


def test_cli_ask_json_and_filters(wired, capsys):
    assert cli.main(["ask", "plaque", "--json", "--as-of", "2023-01-01"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["abstained"] is True and data["abstain_reason"] == "no_passages"     # nothing in force that early
    assert cli.main(["ask", "plaque", "--as-of", "01/02/2024"]) == 2
    assert cli.main(["ask", "plaque", "--meta", "oops"]) == 2


def test_cli_eval_writes_results(wired, tmp_path, capsys):
    csv_path = tmp_path / "q.csv"
    csv_path.write_text("id,category,question,gold_sections,gold_answer,notes\nQ1,single,plaque monument headstone,act:s-2,,\n")
    out = tmp_path / "r.jsonl"
    assert cli.main(["eval", "--questions", str(csv_path), "--out", str(out), "--links"]) == 0
    line = json.loads(out.read_text().splitlines()[0])
    assert line["setup"] == "vector+links" and line["question_id"] == "Q1" and line["retrieved"][0] == "act:s-2"
    assert "1 results" in capsys.readouterr().out
