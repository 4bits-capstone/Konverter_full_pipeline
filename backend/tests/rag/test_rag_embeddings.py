from __future__ import annotations

import httpx
import pytest

from app.rag.embeddings import (
    EmbeddingError, HashEmbedder, OpenAIEmbedder, VoyageEmbedder, build_embedder,
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
