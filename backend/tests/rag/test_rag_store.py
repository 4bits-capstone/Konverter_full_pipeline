from __future__ import annotations

import json

import httpx
import pytest

from app.rag.models import Chunk, Link
from app.rag.settings import ConfigError, RagSettings
from app.rag.store import MemoryStore, StoreError, SupabaseStore, chunk_row, link_rows, vector_literal

KEY = "service-role-SECRET-0987654321"


def make_store(handler):
    settings = RagSettings(supabase_url="https://x.supabase.co/", supabase_key=KEY)
    return SupabaseStore(settings, httpx.Client(transport=httpx.MockTransport(handler)))


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
    assert vector_literal([1, 0.5, -2.25]) == "[1.0,0.5,-2.25]"


def test_upsert_merges_in_batches_of_100_with_the_key_in_headers_only():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201)

    store = make_store(handler)
    store.upsert_chunks([{"chunk_id": f"c{i}"} for i in range(250)])
    assert len(requests) == 3
    r = requests[0]
    assert r.method == "POST" and str(r.url) == "https://x.supabase.co/rest/v1/rag_chunks?on_conflict=chunk_id"
    assert r.headers["prefer"] == "resolution=merge-duplicates,return=minimal"
    assert r.headers["apikey"] == KEY and r.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in r.content.decode() and KEY not in str(r.url)


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
