from __future__ import annotations

import json

import httpx
import pytest

from app.rag.models import Chunk, Link
from app.rag.settings import ConfigError, RagSettings
from app.rag.store import MemoryStore, StoreError, SupabaseStore, chunk_row, link_rows, vector_literal

KEY = "service-role-SECRET-0987654321"


def make_store(handler, sleeps=None, **settings_kw):
    settings = RagSettings(supabase_url="https://x.supabase.co/", supabase_key=KEY, **settings_kw)
    pauses = sleeps if sleeps is not None else []
    return SupabaseStore(settings, httpx.Client(transport=httpx.MockTransport(handler)), sleep=pauses.append, max_attempts=4)


def chunk(**kw) -> Chunk:
    base = dict(chunk_id="act@038:s-1", doc_id="act", doc_type="act", section_id="act:s-1", heading_path=["Act", "Part 1"],
                text="1 Purposes", page_start=11, page_end=11, source_file="a.pdf", version="038", effective_from="2025-10-22")
    return Chunk(**{**base, **kw})


def test_requires_url_and_key():
    with pytest.raises(ConfigError):
        SupabaseStore(RagSettings())


def test_row_carries_every_required_column_and_a_stable_row_hash():
    row = chunk_row(chunk(), "unreviewed")
    for column in ("chunk_id", "doc_id", "version", "doc_type", "section_id", "heading_path", "content", "page_start",
                   "page_end", "source_file", "effective_from", "effective_to", "content_hash", "row_hash", "metadata"):
        assert column in row
    assert row["metadata"]["review_status"] == "unreviewed" and row["version"] == "038"
    assert chunk_row(chunk(), "unreviewed")["row_hash"] == row["row_hash"]
    assert chunk_row(chunk(), "reviewed")["row_hash"] != row["row_hash"]          # metadata change is noticed
    assert chunk_row(chunk(page_end=12), "unreviewed")["row_hash"] != row["row_hash"]
    assert chunk_row(chunk(version=None), "unreviewed")["version"] == ""          # unversioned documents


def test_vector_literal_is_pgvector_text():
    assert vector_literal([1, 0.5, -2.25]) == "[1,0.5,-2.25]"
    # compact: 8 significant digits round-trip float32, about half the bytes of repr()
    v = [0.1234567890123, 1 / 3, -2.5e-07]
    assert vector_literal(v) == "[0.12345679,0.33333333,-2.5e-07]"
    import struct
    assert all(struct.unpack("f", struct.pack("f", float(t)))[0] == struct.unpack("f", struct.pack("f", x))[0]
               for t, x in zip(vector_literal(v).strip("[]").split(","), v))


def test_upsert_merges_in_batches_with_the_key_in_headers_only():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201)

    store = make_store(handler)
    store.upsert_chunks([{"chunk_id": f"c{i}"} for i in range(250)])
    assert len(requests) == 5                                   # default RAG_DB_BATCH is 50
    r = requests[0]
    assert r.method == "POST" and str(r.url) == "https://x.supabase.co/rest/v1/rag_chunks?on_conflict=chunk_id"
    assert r.headers["prefer"] == "resolution=merge-duplicates,return=minimal"
    assert r.headers["apikey"] == KEY and r.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in r.content.decode() and KEY not in str(r.url)


def test_the_batch_size_is_configurable():
    requests = []
    make_store(lambda r: (requests.append(json.loads(r.content)), httpx.Response(201))[1], db_batch=2).upsert_chunks(
        [{"chunk_id": f"c{i}"} for i in range(5)])
    assert [len(r) for r in requests] == [2, 2, 1]


def test_the_client_has_explicit_timeouts():
    store = SupabaseStore(RagSettings(supabase_url="https://x.supabase.co", supabase_key=KEY, db_timeout=45))
    t = store._client.timeout
    assert (t.connect, t.read, t.write, t.pool) == (10.0, 45.0, 45.0, 10.0)


def test_a_write_timeout_is_retried_with_backoff_then_succeeds():
    outcomes = [httpx.WriteTimeout("slow"), httpx.WriteTimeout("slow")]
    calls, pauses = [], []

    def handler(request):
        calls.append(1)
        if outcomes:
            raise outcomes.pop(0)
        return httpx.Response(201)

    make_store(handler, pauses).upsert_chunks([{"chunk_id": "c1"}])
    assert len(calls) == 3 and pauses == [2.0, 4.0]


def test_giving_up_names_the_error_and_the_attempts_without_the_key():
    def handler(request):
        raise httpx.WriteTimeout("slow", request=request)

    pauses = []
    with pytest.raises(StoreError) as err:
        make_store(handler, pauses).upsert_chunks([{"chunk_id": "c1"}])
    assert "POST rag_chunks: request failed (WriteTimeout) after 4 attempts" in str(err.value) and KEY not in str(err.value)
    assert pauses == [2.0, 4.0, 8.0]


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 522])
def test_server_side_errors_are_retried(status):
    responses = [httpx.Response(status, json={"message": "busy"}), httpx.Response(201)]
    pauses = []
    make_store(lambda r: responses.pop(0), pauses).upsert_chunks([{"chunk_id": "c1"}])
    assert pauses == [2.0] and not responses


def test_retry_after_is_honoured():
    responses = [httpx.Response(429, headers={"retry-after": "7"}, json={}), httpx.Response(201)]
    pauses = []
    make_store(lambda r: responses.pop(0), pauses).upsert_chunks([{"chunk_id": "c1"}])
    assert pauses == [7.0]


def test_persistent_server_errors_report_the_attempts():
    with pytest.raises(StoreError, match=r"HTTP 503: busy \(gave up after 4 attempts\)"):
        make_store(lambda r: httpx.Response(503, json={"message": "busy"})).upsert_chunks([{"chunk_id": "c1"}])


def test_client_errors_are_not_retried():
    calls = []
    with pytest.raises(StoreError, match="HTTP 400"):
        make_store(lambda r: (calls.append(1), httpx.Response(400, json={"message": "bad column"}))[1]).upsert_chunks([{"chunk_id": "c1"}])
    assert len(calls) == 1


def test_link_inserts_are_idempotent_upserts():
    seen = []
    make_store(lambda r: (seen.append((r.method, dict(r.url.params), r.headers.get("prefer"))), httpx.Response(201))[1]).replace_links(
        "act", "038", [{"doc_id": "act", "version": "038", "from_section": "a", "to_section": "b", "kind": "refers_to"}])
    assert seen[0][0] == "DELETE"
    assert seen[1][1] == {"on_conflict": "doc_id,version,from_section,to_section,kind"} and "merge-duplicates" in seen[1][2]


def test_existing_chunks_follow_pagination():
    pages = [[{"chunk_id": f"c{i}", "content_hash": "h", "row_hash": "r", "embedding_model": "fake:hash", "embedding_dim": 16}
              for i in range(1000)],
             [{"chunk_id": "last", "content_hash": "h", "row_hash": "r", "embedding_model": None, "embedding_dim": None}]]
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=pages[len(seen) - 1])

    existing = make_store(handler).existing_chunks("act", "038")
    assert len(existing) == 1001 and existing["c0"].fingerprint == "fake:hash:16" and existing["last"].fingerprint is None
    assert seen[0]["doc_id"] == "eq.act" and seen[0]["version"] == "eq.038" and seen[1]["offset"] == "1000"


def test_delete_quotes_ids_that_contain_reserved_characters():
    seen = []
    make_store(lambda r: (seen.append(dict(r.url.params)), httpx.Response(204))[1]).delete_chunks(["act@038:s-3#2", 'a"b,c'])
    assert seen[0]["chunk_id"] == 'in.("act@038:s-3#2","a\\"b,c")'


def test_links_are_replaced_by_delete_then_insert():
    calls = []
    make_store(lambda r: (calls.append((r.method, r.url.path)), httpx.Response(201))[1]).replace_links(
        "act", "038", link_rows("act", "038", [Link("act:s-3", "act:s-40", "refers_to", "act", "section 40")]))
    assert calls == [("DELETE", "/rest/v1/rag_links"), ("POST", "/rest/v1/rag_links")]


def test_server_errors_are_reported_without_leaking_credentials():
    store = make_store(lambda r: httpx.Response(401, json={"message": "Invalid API key"}))
    with pytest.raises(StoreError) as err:
        store.known_sections()
    assert "401" in str(err.value) and "Invalid API key" in str(err.value) and KEY not in str(err.value)

    def boom(request):
        raise httpx.ConnectError("x", request=request)

    with pytest.raises(StoreError, match="ConnectError") as err:
        make_store(boom).known_sections()
    assert KEY not in str(err.value)


def test_match_chunks_rpc_body_matches_the_sql_parameters():
    seen = []
    make_store(lambda r: (seen.append(json.loads(r.content)), httpx.Response(200, json=[]))[1]).match_chunks(
        [0.5, 0.25], k=7, doc_ids=["act"], as_of_date="2025-01-01", meta_filter={"review_status": "reviewed"})
    assert seen[0] == {"query_embedding": "[0.5,0.25]", "k": 7, "doc_ids": ["act"], "as_of_date": "2025-01-01",
                       "meta_filter": {"review_status": "reviewed"}}


def test_memory_store_keeps_the_embedding_on_a_metadata_only_upsert():
    store = MemoryStore()
    store.upsert_chunks([{**chunk_row(chunk(), "unreviewed"), "embedding": "[1.0,0.0]", "embedding_model": "m", "embedding_dim": 2}])
    store.upsert_chunks([chunk_row(chunk(), "reviewed")])                      # no embedding keys
    row = store.chunks["act@038:s-1"]
    assert row["embedding"] == "[1.0,0.0]" and row["metadata"]["review_status"] == "reviewed"
