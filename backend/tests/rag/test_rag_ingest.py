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


# --- resilience: write each batch as soon as it is embedded; delete only at the very end ---------------

import logging

from app.rag.embeddings import EmbeddingError
from app.rag.store import StoreError


class FlakyEmbedder(HashEmbedder):
    """Fails (like a Voyage 429 that outlasted its retries) on the n-th embed call."""

    def __init__(self, fail_on=None, batch_size=2):
        super().__init__(16, batch_size=batch_size)
        self.fail_on, self.attempts = fail_on, 0

    def embed(self, texts, input_type="document"):
        self.attempts += 1
        if self.attempts == self.fail_on:
            raise EmbeddingError("voyage: HTTP 429: Rate limit reached (gave up after 8 attempts)")
        return super().embed(texts, input_type)


class FlakyStore(MemoryStore):
    def __init__(self, fail_upsert_on=None, fail_links=False):
        super().__init__()
        self.fail_upsert_on, self.fail_links, self.upserts = fail_upsert_on, fail_links, 0

    def upsert_chunks(self, rows):
        self.upserts += 1
        if self.upserts == self.fail_upsert_on:
            raise StoreError("POST rag_chunks: request failed (WriteTimeout) after 5 attempts")
        super().upsert_chunks(rows)

    def replace_links(self, doc_id, version, rows):
        if self.fail_links:
            raise StoreError("POST rag_links: request failed (WriteTimeout) after 5 attempts")
        super().replace_links(doc_id, version, rows)


def act(version, sections, effective_from="2024-01-01", effective_to=None) -> Source:
    """sections: [(number, title, text)] -> a small Act, one chunk per section."""
    info = DocumentInfo(doc_id="act", doc_type="act", title="Test Act 2000", version=version, published="2024-01-01",
                        effective_from=effective_from, effective_to=effective_to, file=f"act{version}.pdf")
    blocks = [{"type": "heading", "level": 3, "text": "Part 1 — Preliminary", "page": 1}]
    for number, title, text in sections:
        blocks += [{"type": "heading", "level": 5, "text": f"{number} {title}", "page": number},
                   {"type": "paragraph", "text": text, "page": number, "number": None}]
    structured = {"publication": {"sections": [{"id": "document-body", "title": "Document", "page": 1, "blocks": blocks}]}}
    return Source(f"act@{version}", info, structured, "unreviewed")


def seven_sections(**kw):
    names = ["Ledger register kept", "Plaque monument headstone", "Assignment conveyance price", "Levy tariff schedule",
             "Inhumation plot burial", "Desecration vandalism offence", "Exhumation licence permit"]
    sections = [(i + 1, f"Section {i + 1}", f"{names[i]} number {i + 1}. See section 1." if i else names[i]) for i in range(7)]
    return act("038", sections, **kw)


def test_a_rate_limited_run_keeps_the_batches_already_embedded_and_resumes_without_paying_twice():
    store, first = MemoryStore(), FlakyEmbedder(fail_on=3)
    with pytest.raises(EmbeddingError) as err:
        ingest([seven_sections()], first, store, SETTINGS)
    assert "4 of 7 new chunks of act@038 were stored" in str(err.value) and "run the same command again" in str(err.value)
    assert len(store.chunks) == 4 and all(r["embedding"] for r in store.chunks.values())
    assert ("act", "038") not in store.documents                       # the document row is the last thing written
    second = FlakyEmbedder()
    results = ingest([seven_sections()], second, store, SETTINGS)
    assert second.texts_embedded == 3 and results[0].embedded == 3 and results[0].unchanged == 4
    assert len(store.chunks) == 7 and ("act", "038") in store.documents
    assert first.texts_embedded + second.texts_embedded == 7          # 4 + 3: nothing embedded twice
    third = FlakyEmbedder()
    ingest([seven_sections()], third, store, SETTINGS)
    assert third.texts_embedded == 0


def test_a_failed_database_write_loses_at_most_the_batch_in_flight():
    store, first = FlakyStore(fail_upsert_on=3), FlakyEmbedder()
    with pytest.raises(StoreError) as err:
        ingest([seven_sections()], first, store, SETTINGS)
    assert "WriteTimeout" in str(err.value) and "4 of 7 new chunks" in str(err.value)
    assert len(store.chunks) == 4
    assert first.texts_embedded == 6                                  # the third batch was embedded, but its write failed
    second = FlakyEmbedder()
    store.fail_upsert_on = None
    ingest([seven_sections()], second, store, SETTINGS)
    assert len(store.chunks) == 7 and second.texts_embedded == 3


def vanishing_pair():
    old = seven_sections()
    new = seven_sections()
    section = new.structured["publication"]["sections"][0]
    blocks = section["blocks"]
    # drop sections 6 and 7, change the text of 2 and 3, add section 8
    keep = [b for b in blocks if not str(b.get("text", "")).startswith(("6 Section", "7 Section", "Desecration", "Exhumation"))]
    for b in keep:
        if b.get("text", "").startswith(("Plaque", "Assignment")):
            b["text"] += " Amended."
    keep += [{"type": "heading", "level": 5, "text": "8 Section 8", "page": 8}, {"type": "paragraph", "text": "Brand new clause.", "page": 8, "number": None}]
    section["blocks"] = keep
    return old, new


def test_vanished_sections_are_deleted_only_after_every_write_succeeded():
    old, new = vanishing_pair()
    store = MemoryStore()
    ingest([old], FlakyEmbedder(), store, SETTINGS)
    assert {"act@038:s-6", "act@038:s-7"} <= set(store.chunks)
    with pytest.raises(EmbeddingError):
        ingest([new], FlakyEmbedder(fail_on=2), store, SETTINGS)
    assert {"act@038:s-6", "act@038:s-7"} <= set(store.chunks), "nothing may be deleted while writes are still failing"
    with pytest.raises(StoreError):
        ingest([new], FlakyEmbedder(), FlakyStoreFrom(store, fail_links=True), SETTINGS)
    assert {"act@038:s-6", "act@038:s-7"} <= set(store.chunks), "a failed links write must not trigger deletion either"
    results = ingest([new], FlakyEmbedder(), store, SETTINGS)
    assert not {"act@038:s-6", "act@038:s-7"} & set(store.chunks) and "act@038:s-8" in store.chunks
    assert results[0].deleted == 2


def FlakyStoreFrom(store: MemoryStore, fail_links: bool) -> FlakyStore:
    flaky = FlakyStore(fail_links=fail_links)
    flaky.chunks, flaky.documents, flaky.links = store.chunks, store.documents, store.links      # same data, failing links write
    return flaky


def test_progress_is_logged_per_batch(caplog):
    with caplog.at_level(logging.INFO, logger="konverter.rag.ingest"):
        ingest([seven_sections()], FlakyEmbedder(), MemoryStore(), SETTINGS)
    messages = [r.getMessage() for r in caplog.records if "embedded and stored batch" in r.getMessage()]
    assert messages[0].endswith("batch 1/4 (2/7 chunks)") and messages[-1].endswith("batch 4/4 (7/7 chunks)")
