from __future__ import annotations

import json

import httpx
import pytest

from app.rag.embeddings import (
    EmbeddingError, HashEmbedder, OpenAIEmbedder, VoyageEmbedder, build_embedder, estimate_tokens, plan_batches,
)
from app.rag.settings import ConfigError, RagSettings, load_rag_settings

KEY = "sk-test-SECRET-1234567890"


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok(texts: int, dim: int, status: int = 200):
    # returned out of order on purpose: the embedder must sort by "index"
    data = [{"index": i, "embedding": [float(i)] * dim} for i in reversed(range(texts))]
    return httpx.Response(status, json={"data": data})


# --- settings ---------------------------------------------------------------------------------

def test_defaults_come_from_one_place_and_are_overridable():
    s = load_rag_settings({})
    assert (s.embed_provider, s.embed_model, s.embed_dim) == ("voyage", "voyage-law-2", 1024)
    s = load_rag_settings({"RAG_EMBED_PROVIDER": "openai", "RAG_EMBED_DIM": "1536", "OPENAI_API_KEY": KEY})
    assert (s.embed_provider, s.embed_model, s.embed_dim) == ("openai", "text-embedding-3-small", 1536)
    assert load_rag_settings({"RAG_EMBED_MODEL": "voyage-3-large"}).embed_model == "voyage-3-large"
    assert s.embed_fingerprint == "openai:text-embedding-3-small:1536"


@pytest.mark.parametrize("env", [{"RAG_EMBED_PROVIDER": "cohere"}, {"RAG_EMBED_DIM": "0"}, {"RAG_EMBED_DIM": "4096"},
                                 {"RAG_EMBED_DIM": "abc"}, {"RAG_EMBED_BATCH": "0"}])
def test_bad_configuration_is_rejected(env):
    with pytest.raises(ConfigError):
        load_rag_settings(env)


def test_secrets_never_appear_in_repr():
    s = load_rag_settings({"VOYAGE_API_KEY": KEY, "SUPABASE_SERVICE_ROLE_KEY": KEY, "OPENAI_API_KEY": KEY})
    assert KEY not in repr(s)


# --- voyage ---------------------------------------------------------------------------------

def test_voyage_request_shape_and_ordering():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return ok(len(request.read() and __import__("json").loads(request.content)["input"]), 4)

    e = VoyageEmbedder("voyage-law-2", 4, KEY, client=client(handler))
    vectors = e.embed(["a", "b", "c"], "query")
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]
    body = __import__("json").loads(seen[0].content)
    assert body == {"model": "voyage-law-2", "input": ["a", "b", "c"], "input_type": "query"}
    assert seen[0].url == "https://api.voyageai.com/v1/embeddings"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in seen[0].content.decode()          # the key travels in a header only


def test_batches_are_split_to_the_configured_size():
    def handler(request):
        return ok(len(__import__("json").loads(request.content)["input"]), 3)

    e = VoyageEmbedder("m", 3, KEY, batch_size=2, client=client(handler))
    assert len(e.embed([str(i) for i in range(5)])) == 5
    assert e.calls == 3 and e.texts_embedded == 5


def test_rate_limits_are_retried_with_backoff_then_succeed():
    responses = [httpx.Response(429, headers={"retry-after": "2"}, json={}), httpx.Response(503, json={})]
    sleeps = []

    def handler(request):
        return responses.pop(0) if responses else ok(1, 2)

    e = VoyageEmbedder("m", 2, KEY, client=client(handler), sleep=sleeps.append)
    assert e.embed(["x"]) == [[0.0, 0.0]]
    assert sleeps[0] == 2.0 and len(sleeps) == 2 and e.calls == 3


def test_gives_up_after_max_attempts_without_leaking_the_key():
    e = VoyageEmbedder("m", 2, KEY, client=client(lambda r: httpx.Response(500, json={"detail": "boom"})),
                       sleep=lambda s: None, max_attempts=3)
    with pytest.raises(EmbeddingError) as err:
        e.embed(["x"])
    assert "500" in str(err.value) and KEY not in str(err.value) and e.calls == 3


def test_client_errors_fail_fast_with_the_providers_message():
    e = VoyageEmbedder("m", 2, KEY, client=client(lambda r: httpx.Response(401, json={"detail": "Provided API key is invalid."})))
    with pytest.raises(EmbeddingError) as err:
        e.embed(["x"])
    assert "401" in str(err.value) and "invalid" in str(err.value) and e.calls == 1 and KEY not in str(err.value)


def test_a_dimension_mismatch_is_an_error_not_a_silent_truncation():
    e = VoyageEmbedder("voyage-law-2", 1024, KEY, client=client(lambda r: ok(1, 512)))
    with pytest.raises(EmbeddingError, match="512 dimensions but RAG_EMBED_DIM is 1024"):
        e.embed(["x"])


def test_transport_errors_are_reported_without_the_url_or_key():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    e = VoyageEmbedder("m", 2, KEY, client=client(handler), sleep=lambda s: None, max_attempts=2)
    with pytest.raises(EmbeddingError, match="ConnectError") as err:
        e.embed(["x"])
    assert KEY not in str(err.value)


# --- openai ---------------------------------------------------------------------------------

def test_openai_asks_text_embedding_3_for_the_configured_dimension():
    seen = []

    def handler(request):
        seen.append(__import__("json").loads(request.content))
        return ok(1, 1024)

    OpenAIEmbedder("text-embedding-3-small", 1024, KEY, client=client(handler)).embed(["x"], "document")
    assert seen[0] == {"model": "text-embedding-3-small", "input": ["x"], "dimensions": 1024}


def test_openai_does_not_send_dimensions_to_models_that_reject_it():
    seen = []

    def handler(request):
        seen.append(__import__("json").loads(request.content))
        return ok(1, 1536)

    OpenAIEmbedder("text-embedding-ada-002", 1536, KEY, client=client(handler)).embed(["x"])
    assert "dimensions" not in seen[0]


# --- factory and fake -----------------------------------------------------------------------

def test_factory_follows_the_configured_provider_and_requires_its_key():
    s = RagSettings(embed_provider="openai", embed_model="text-embedding-3-small", embed_dim=1024, openai_api_key=KEY)
    e = build_embedder(s)
    assert isinstance(e, OpenAIEmbedder) and (e.model, e.dimension) == ("text-embedding-3-small", 1024)
    assert isinstance(build_embedder(RagSettings(voyage_api_key=KEY)), VoyageEmbedder)
    with pytest.raises(ConfigError, match="VOYAGE_API_KEY"):
        build_embedder(RagSettings())


def test_hash_embedder_is_deterministic_and_normalised():
    e = HashEmbedder(8)
    a, b = e.embed(["right of interment", "right of interment"])
    assert a == b and abs(sum(x * x for x in a) - 1.0) < 1e-9
    assert e.embed(["completely different words"])[0] != a


# --- rate limits, timeouts, token-sized batches --------------------------------------------------------

def test_a_429_without_retry_after_backs_off_longer_and_is_capped():
    responses = [httpx.Response(429, json={}) for _ in range(7)] + [ok(1, 2)]
    sleeps = []
    e = VoyageEmbedder("m", 2, KEY, client=client(lambda r: responses.pop(0)), sleep=sleeps.append, max_attempts=8)
    assert e.embed(["x"]) == [[0.0, 0.0]]
    assert sleeps == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0, 60.0]


def test_retry_after_wins_and_is_capped_at_five_minutes():
    responses = [httpx.Response(429, headers={"retry-after": "12"}, json={}),
                 httpx.Response(429, headers={"retry-after": "99999"}, json={}), ok(1, 2)]
    sleeps = []
    VoyageEmbedder("m", 2, KEY, client=client(lambda r: responses.pop(0)), sleep=sleeps.append).embed(["x"])
    assert sleeps == [12.0, 300.0]


def test_persistent_rate_limiting_is_reported_with_the_attempt_count():
    e = VoyageEmbedder("m", 2, KEY, client=client(lambda r: httpx.Response(429, json={"detail": "Rate limit reached"})),
                       sleep=lambda s: None, max_attempts=3)
    with pytest.raises(EmbeddingError, match=r"HTTP 429: Rate limit reached \(gave up after 3 attempts\)"):
        e.embed(["x"])


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.WriteTimeout("t"), httpx.ConnectTimeout("t"), httpx.ReadError("r")])
def test_timeouts_and_resets_are_retried(exc):
    outcomes = [exc]

    def handler(request):
        if outcomes:
            raise outcomes.pop(0)
        return ok(1, 2)

    sleeps = []
    assert VoyageEmbedder("m", 2, KEY, client=client(handler), sleep=sleeps.append).embed(["x"]) == [[0.0, 0.0]]
    assert sleeps == [2.0]


def test_the_default_client_has_explicit_timeouts():
    t = VoyageEmbedder("m", 2, KEY).__dict__["_client"].timeout
    assert (t.connect, t.write) == (10.0, 60.0) and t.read >= 60.0


def test_batches_are_sized_by_estimated_tokens_as_well_as_count():
    texts = ["a" * 300] * 10                                  # 100 tokens each
    assert estimate_tokens("a" * 300) == 100
    groups = plan_batches(texts, max_items=64, max_tokens=350)
    assert [len(g) for g in groups] == [3, 3, 3, 1] and [i for g in groups for i in g] == list(range(10))
    assert [len(g) for g in plan_batches(texts, max_items=4, max_tokens=10**6)] == [4, 4, 2]
    assert plan_batches(["a" * 3000, "b", "c"], max_items=64, max_tokens=500) == [[0], [1, 2]]      # an oversize text rides alone
    assert plan_batches([], 64, 1000) == []


def test_embed_sends_one_request_per_token_batch_in_order_and_counts_provider_tokens():
    seen = []

    def handler(request):
        batch = json.loads(request.content)["input"]
        seen.append(batch)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [float(len(t)), 0.0]} for i, t in enumerate(batch)],
                                         "usage": {"total_tokens": 7}})

    e = VoyageEmbedder("m", 2, KEY, batch_size=64, batch_tokens=1000, client=client(handler))
    texts = ["x" * 1500, "y" * 1500, "z" * 1500, "w" * 30]           # 500 tokens each, last tiny
    vectors = e.embed(texts)
    assert [len(b) for b in seen] == [2, 2] and [v[0] for v in vectors] == [1500.0, 1500.0, 1500.0, 30.0]
    assert e.calls == 2 and e.tokens == 14


def test_batch_limits_come_from_settings():
    s = RagSettings(voyage_api_key=KEY, embed_batch=5, embed_batch_tokens=2000, embed_max_retries=3)
    e = build_embedder(s)
    assert (e.batch_size, e.batch_tokens, e._attempts) == (5, 2000, 3)
    c = load_rag_settings({"RAG_EMBED_BATCH_TOKENS": "5000", "RAG_EMBED_MAX_RETRIES": "10", "RAG_DB_BATCH": "25", "RAG_DB_TIMEOUT": "90"})
    assert (c.embed_batch_tokens, c.embed_max_retries, c.db_batch, c.db_timeout) == (5000, 10, 25, 90.0)
    for env in ({"RAG_EMBED_BATCH_TOKENS": "10"}, {"RAG_DB_BATCH": "0"}, {"RAG_DB_TIMEOUT": "0"}, {"RAG_EMBED_MAX_RETRIES": "0"}):
        with pytest.raises(ConfigError):
            load_rag_settings(env)
