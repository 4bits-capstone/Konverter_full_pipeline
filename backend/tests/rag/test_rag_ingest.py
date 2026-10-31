from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.rag import ingest as ingest_module
from app.rag.embeddings import HashEmbedder
from app.rag.ingest import Source, ingest, load_or_convert, plan_sync
from app.rag.models import DocumentInfo, load_manifest
from app.rag.settings import RagSettings
from app.rag.store import ExistingChunk, MemoryStore

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = load_manifest(FIXTURES / "documents.json")
SETTINGS = RagSettings()


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def sources(status: str = "unreviewed") -> list[Source]:
    return [
        Source("report", MANIFEST["report"], fixture("report"), status),
        Source("paper", MANIFEST["paper"], fixture("paper"), status),
        Source("act@038", MANIFEST["act@038"], fixture("act_part6"), status),
    ]


def run(srcs, store, embedder=None, **kw):
    embedder = embedder or HashEmbedder(16)
    return ingest(srcs, embedder, store, SETTINGS, **kw), embedder


def synthetic(doc_id="act", version="037", text="A holder may inter remains.", effective_from="2024-01-01", effective_to=None,
              extra_para=None) -> Source:
    info = DocumentInfo(doc_id=doc_id, doc_type="act", title="Test Act 2000", version=version, published="2024-01-01",
                        effective_from=effective_from, effective_to=effective_to, file="t.pdf")
    blocks = [{"type": "heading", "level": 3, "text": "Part 1 — Preliminary", "page": 1},
              {"type": "heading", "level": 5, "text": "1 Entitlements", "page": 1},
              {"type": "paragraph", "text": text, "page": 1, "number": None},
              {"type": "heading", "level": 5, "text": "2 Transfer", "page": 2},
              {"type": "paragraph", "text": "See section 1 for who may transfer.", "page": 2, "number": None}]
    if extra_para:
        blocks += [{"type": "heading", "level": 5, "text": "3 Extra", "page": 3}, {"type": "paragraph", "text": extra_para, "page": 3, "number": None}]
    structured = {"publication": {"sections": [{"id": "document-body", "title": "Document", "page": 1, "blocks": blocks}]}}
    return Source(f"{doc_id}@{version}", info, structured, "unreviewed")


# --- idempotence -----------------------------------------------------------------------------

def test_first_ingest_stores_complete_rows_with_embeddings():
    store = MemoryStore()
    results, embedder = run(sources(), store)
    total = sum(r.chunks for r in results)
    assert total == len(store.chunks) and embedder.texts_embedded == total
    for row in store.chunks.values():
        for column in ("chunk_id", "doc_id", "doc_type", "section_id", "heading_path", "version", "effective_from",
                       "page_start", "page_end", "source_file", "content_hash", "content"):
            assert row[column] not in (None, "") or column == "version", column
        assert json.loads(row["embedding"]) and len(json.loads(row["embedding"])) == 16
        assert (row["embedding_model"], row["embedding_dim"]) == ("fake:hash", 16)
        assert row["metadata"]["review_status"] == "unreviewed"
    assert set(store.documents) == {("report", ""), ("paper", ""), ("act", "038")}
    assert store.documents[("act", "038")]["chunk_count"] == len([r for r in store.chunks.values() if r["doc_id"] == "act"])


def test_rerun_on_unchanged_input_embeds_nothing_and_writes_nothing():
    store = MemoryStore()
    run(sources(), store)
    writes = store.writes
    results, embedder = run(sources(), store)
    assert embedder.texts_embedded == 0 and embedder.calls == 0
    assert store.writes == writes
    assert all(r.embedded == r.deleted == r.metadata_updated == 0 and r.unchanged == r.chunks for r in results)
    assert not any(r.links_written for r in results)


def test_only_the_chunk_whose_text_changed_is_re_embedded():
    store = MemoryStore()
    run(sources(), store)
    before = copy.deepcopy(store.chunks)
    changed = sources()
    block = next(b for s in changed[0].structured["publication"]["sections"] for b in s["blocks"]
                 if b.get("number") == "6.25")
    block["text"] += " An amendment."
    results, embedder = run(changed, store)
    assert embedder.texts_embedded == 1 and sum(r.embedded for r in results) == 1
    row = store.chunks["report:para-6.25"]
    assert row["embedding"] != before["report:para-6.25"]["embedding"] and "An amendment." in row["content"]
    assert all(store.chunks[c]["embedding"] == before[c]["embedding"] for c in before if c != "report:para-6.25")


def test_a_different_embedding_model_re_embeds_everything():
    store = MemoryStore()
    results, _ = run(sources(), store)
    again, embedder = run(sources(), store, HashEmbedder(16, model="hash-v2"))
    assert embedder.texts_embedded == sum(r.chunks for r in results) == sum(r.embedded for r in again)
    assert {r["embedding_model"] for r in store.chunks.values()} == {"fake:hash-v2"}
    _, same = run(sources(), store, HashEmbedder(16, model="hash-v2"))
    assert same.texts_embedded == 0


def test_a_different_dimension_also_counts_as_a_different_model():
    store = MemoryStore()
    run(sources(), store, HashEmbedder(16))
    _, embedder = run(sources(), store, HashEmbedder(32))
    assert embedder.texts_embedded > 0


def test_a_metadata_only_change_updates_rows_without_calling_the_embedder():
    store = MemoryStore()
    run(sources("unreviewed"), store)
    vectors = {c: r["embedding"] for c, r in store.chunks.items()}
    results, embedder = run(sources("reviewed"), store)
    assert embedder.texts_embedded == 0 and sum(r.metadata_updated for r in results) == len(store.chunks)
    assert all(r["metadata"]["review_status"] == "reviewed" and r["embedding"] == vectors[c] for c, r in store.chunks.items())
    assert store.documents[("report", "")]["review_status"] == "reviewed"


def test_chunks_of_sections_that_disappeared_are_deleted():
    store = MemoryStore()
    run(sources(), store)
    shrunk = sources()
    section = shrunk[2].structured["publication"]["sections"][0]
    section["blocks"] = [b for b in section["blocks"] if not str(b.get("text", "")).startswith(("79 ", "80 "))]
    results, embedder = run(shrunk, store)
    gone = {"act@038:s-79", "act@038:s-80"}
    assert gone.isdisjoint(store.chunks) and embedder.texts_embedded == 0
    assert sum(r.deleted for r in results) >= 2
    assert "act@038:s-78" in store.chunks


def test_dry_run_reports_but_touches_nothing():
    store = MemoryStore()
    results, embedder = run(sources(), store, dry_run=True)
    assert store.writes == 0 and not store.chunks and embedder.texts_embedded == 0
    assert sum(r.embedded for r in results) > 0


def test_documents_are_isolated_from_each_other():
    store = MemoryStore()
    run(sources(), store)
    _, embedder = run(sources()[:1], store)            # re-ingesting the report alone leaves the others untouched
    assert embedder.texts_embedded == 0 and {r["doc_id"] for r in store.chunks.values()} == {"report", "paper", "act"}


# --- links ------------------------------------------------------------------------------------

def test_links_are_stored_once_and_not_rewritten_when_unchanged():
    store = MemoryStore()
    results, _ = run([synthetic()], store)
    assert store.links[("act", "037")][0]["from_section"] == "act:s-2" and store.links[("act", "037")][0]["to_section"] == "act:s-1"
    assert results[0].links == 1 and results[0].links_written
    writes = store.writes
    again, _ = run([synthetic()], store)
    assert not again[0].links_written and store.writes == writes


def test_links_resolve_against_sections_already_in_the_store():
    store = MemoryStore()
    run([sources()[1]], store)                                    # the paper first
    info = replace(MANIFEST["report"])
    structured = {"publication": {"sections": [{"id": "x", "title": "Ch 5", "page": 1, "blocks": [
        {"type": "heading", "level": 1, "text": "5. Options", "page": 1},
        {"type": "paragraph", "text": "The Consultation Paper asked in Question 4 whether to change the law.", "page": 1, "number": "5.1"}]}]}}
    run([Source("report", info, structured, "reviewed")], store)
    assert {(l["from_section"], l["to_section"], l["kind"]) for l in store.links[("report", "")]} == {
        ("report:para-5.1", "paper:q-4", "responds_to")}


# --- retrieval semantics shared with the SQL function ---------------------------------------------

def embed_query(text: str) -> list[float]:
    return HashEmbedder(16).embed([text])[0]


def test_the_date_filter_excludes_versions_that_are_not_in_force():
    store = MemoryStore()
    old = synthetic(version="037", text="A holder may inter remains.", effective_from="2024-01-01", effective_to="2025-10-22")
    new = synthetic(version="038", text="A holder may inter remains and install a memorial.", effective_from="2025-10-22")
    run([old, new], store)
    q = embed_query("holder may inter remains")
    versions = lambda **kw: {h["version"] for h in store.match_chunks(q, k=50, **kw)}
    assert versions(as_of_date="2025-01-01") == {"037"}
    assert versions(as_of_date="2025-10-21") == {"037"}
    assert versions(as_of_date="2025-10-22") == {"038"}          # effective_to is exclusive, effective_from inclusive
    assert versions(as_of_date="2026-06-01") == {"038"}
    assert versions(as_of_date="2023-01-01") == set()            # before either was in force
    assert versions() == {"037", "038"}
    assert {h["chunk_id"] for h in store.match_chunks(q, k=50, as_of_date="2025-01-01")} <= {
        "act@037:s-1", "act@037:s-2"}


def test_a_doc_ids_filtered_query_still_returns_k_rows():
    store = MemoryStore()
    run(sources(), store)
    q = embed_query("funeral and burial instructions agent")
    for doc_id, k in (("act", 5), ("paper", 25), ("report", 40)):
        hits = store.match_chunks(q, k=k, doc_ids=[doc_id])
        assert len(hits) == k and {h["doc_id"] for h in hits} == {doc_id}
        assert [h["similarity"] for h in hits] == sorted((h["similarity"] for h in hits), reverse=True)
    assert len(store.match_chunks(q, k=7, doc_ids=["act", "paper"])) == 7
    assert {h["doc_id"] for h in store.match_chunks(q, k=500, doc_ids=["act"])} == {"act"}
    assert len(store.match_chunks(q, k=10_000, doc_ids=["act"])) == len([r for r in store.chunks.values() if r["doc_id"] == "act"])


def test_metadata_filter_selects_reviewed_documents():
    store = MemoryStore()
    run([sources("reviewed")[0], sources("unreviewed")[1]], store)
    q = embed_query("funeral")
    assert {h["doc_id"] for h in store.match_chunks(q, k=500, meta_filter={"review_status": "reviewed"})} == {"report"}
    assert {h["doc_id"] for h in store.match_chunks(q, k=500, meta_filter={"review_status": "unreviewed"})} == {"paper"}


# --- planning and sources ---------------------------------------------------------------------

def test_plan_sync_classifies_each_chunk():
    rows = {"new": {"content_hash": "h1", "row_hash": "r1"}, "same": {"content_hash": "h2", "row_hash": "r2"},
            "meta": {"content_hash": "h3", "row_hash": "r3-new"}, "text": {"content_hash": "h4-new", "row_hash": "r4"},
            "model": {"content_hash": "h5", "row_hash": "r5"}}
    old = {
        "same": ExistingChunk("same", "h2", "r2", "p:m", 4), "meta": ExistingChunk("meta", "h3", "r3", "p:m", 4),
        "text": ExistingChunk("text", "h4", "r4", "p:m", 4), "model": ExistingChunk("model", "h5", "r5", "p:other", 4),
        "gone": ExistingChunk("gone", "h6", "r6", "p:m", 4),
    }
    plan = plan_sync(old, rows, "p:m:4")
    assert (sorted(plan.embed), plan.update_meta, plan.unchanged, plan.delete) == (["model", "new", "text"], ["meta"], ["same"], ["gone"])
    assert plan_sync({"x": ExistingChunk("x", "h", "r", None, None)}, {"x": {"content_hash": "h", "row_hash": "r"}}, "p:m:4").embed == ["x"]


def test_a_structured_json_beside_the_pdf_is_used_without_converting(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-fake")
    (tmp_path / "a.structured.json").write_text(json.dumps({"publication": {"sections": []}}))
    monkeypatch.setattr(ingest_module, "convert_pdf", lambda p: pytest.fail("must not convert"))
    structured, origin = load_or_convert(pdf, RagSettings(cache_dir=tmp_path / "cache"))
    assert structured == {"publication": {"sections": []}} and "beside" in origin


def test_conversion_is_cached_by_pdf_hash(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-fake")
    calls = []
    monkeypatch.setattr(ingest_module, "convert_pdf", lambda p: calls.append(p) or {"publication": {"sections": [1]}})
    settings = RagSettings(cache_dir=tmp_path / "cache")
    assert load_or_convert(pdf, settings)[1] == "converted"
    assert load_or_convert(pdf, settings)[1] == "cache" and len(calls) == 1
    assert load_or_convert(pdf, settings, reconvert=True)[1] == "converted" and len(calls) == 2
    pdf.write_bytes(b"%PDF-changed")                   # a changed file is a different cache key
    assert load_or_convert(pdf, settings)[1] == "converted" and len(calls) == 3
