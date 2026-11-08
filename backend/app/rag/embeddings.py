"""One embedding interface; Voyage and OpenAI behind it, a deterministic fake for tests.

Provider, model and dimension come from RagSettings. A response whose vector length differs from
the configured dimension is an error, never silently truncated or padded.
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from typing import Callable, Literal, Protocol, Sequence

import httpx

from .settings import ConfigError, RagSettings

InputType = Literal["document", "query"]
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
OPENAI_URL = "https://api.openai.com/v1/embeddings"
_RETRY_STATUS = {429, 500, 502, 503, 504}
log = logging.getLogger("konverter.rag.embeddings")
MAX_WAIT = 60.0           # longest pause between attempts when the server does not say
MAX_RETRY_AFTER = 300.0   # longest Retry-After we are willing to honour


def estimate_tokens(text: str) -> int:
    """Deliberately generous (3 characters per token; English legal text is nearer 4)."""
    return max(1, math.ceil(len(text) / 3))


def plan_batches(texts: Sequence[str], max_items: int, max_tokens: int) -> list[list[int]]:
    """Indices of `texts` grouped in order so no group exceeds `max_items` texts or `max_tokens` estimated tokens.
    A single text over the token limit gets a group of its own."""
    groups: list[list[int]] = []
    current: list[int] = []
    used = 0
    for index, text in enumerate(texts):
        tokens = estimate_tokens(text)
        if current and (len(current) >= max_items or used + tokens > max_tokens):
            groups.append(current)
            current, used = [], 0
        current.append(index)
        used += tokens
    if current:
        groups.append(current)
    return groups


class EmbeddingError(RuntimeError):
    """Carries the HTTP status and a short provider message, never a request header or key."""


class Embedder(Protocol):
    provider: str
    model: str
    dimension: int
    calls: int            # HTTP calls made (observability and tests)
    texts_embedded: int

    def plan_batches(self, texts: Sequence[str]) -> list[list[int]]: ...
    def embed(self, texts: Sequence[str], input_type: InputType = "document") -> list[list[float]]: ...


class _HttpEmbedder:
    provider = ""

    def __init__(
        self,
        model: str,
        dimension: int,
        api_key: str,
        batch_size: int = 64,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 8,
        batch_tokens: int = 30_000,
    ) -> None:
        if not api_key:
            raise ConfigError(f"{self.key_name} is not set")
        self.model, self.dimension, self._key = model, dimension, api_key
        self.batch_size, self.batch_tokens = batch_size, batch_tokens
        self._client = client or httpx.Client(timeout=httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=10.0))
        self._sleep, self._attempts = sleep, max_attempts
        self.calls = 0
        self.texts_embedded = 0
        self.tokens = 0         # as reported by the provider

    key_name = ""
    url = ""

    def _payload(self, batch: Sequence[str], input_type: InputType) -> dict:
        raise NotImplementedError

    def plan_batches(self, texts: Sequence[str]) -> list[list[int]]:
        return plan_batches(texts, self.batch_size, self.batch_tokens)

    def embed(self, texts: Sequence[str], input_type: InputType = "document") -> list[list[float]]:
        out: list[list[float]] = []
        for group in self.plan_batches(texts):
            out += self._embed_batch([texts[i] for i in group], input_type)
        self.texts_embedded += len(texts)
        return out

    def _wait(self, attempt: int, response: httpx.Response | None) -> float:
        """Honour Retry-After; otherwise back off (longer after a 429, which means "slow down")."""
        header = response.headers.get("retry-after", "") if response is not None else ""
        if header.replace(".", "", 1).isdigit():
            return min(float(header), MAX_RETRY_AFTER)
        base = 5.0 if response is not None and response.status_code == 429 else 2.0
        return min(base * 2 ** (attempt - 1), MAX_WAIT)

    def _embed_batch(self, batch: list[str], input_type: InputType) -> list[list[float]]:
        for attempt in range(1, self._attempts + 1):
            self.calls += 1
            try:
                response = self._client.post(
                    self.url, json=self._payload(batch, input_type), headers={"Authorization": f"Bearer {self._key}"}
                )
            except httpx.TransportError as exc:          # timeouts, resets, DNS: all worth another try
                if attempt == self._attempts:
                    raise EmbeddingError(f"{self.provider}: request failed ({type(exc).__name__}) after {attempt} attempts") from None
                wait = self._wait(attempt, None)
                log.warning("%s: %s, retrying in %.0fs (attempt %d/%d)", self.provider, type(exc).__name__, wait, attempt, self._attempts)
                self._sleep(wait)
                continue
            if response.status_code in _RETRY_STATUS and attempt < self._attempts:
                wait = self._wait(attempt, response)
                log.warning("%s: HTTP %d, retrying in %.0fs (attempt %d/%d)", self.provider, response.status_code, wait, attempt, self._attempts)
                self._sleep(wait)
                continue
            if response.status_code >= 400:
                tail = f" (gave up after {attempt} attempts)" if response.status_code in _RETRY_STATUS else ""
                raise EmbeddingError(f"{self.provider}: HTTP {response.status_code}: {_short(response)}{tail}")
            body = response.json()
            vectors = self._parse(body, len(batch))
            self.tokens += int((body.get("usage") or {}).get("total_tokens") or 0)
            for vector in vectors:
                if len(vector) != self.dimension:
                    raise EmbeddingError(
                        f"{self.provider}: model {self.model!r} returned {len(vector)} dimensions but "
                        f"RAG_EMBED_DIM is {self.dimension}; fix the configuration (and the SQL) to match"
                    )
            return vectors
        raise EmbeddingError(f"{self.provider}: gave up after {self._attempts} attempts")  # pragma: no cover

    @staticmethod
    def _parse(body: dict, expected: int) -> list[list[float]]:
        data = sorted(body.get("data") or [], key=lambda item: item.get("index", 0))
        if len(data) != expected:
            raise EmbeddingError(f"expected {expected} embeddings, got {len(data)}")
        return [list(map(float, item["embedding"])) for item in data]


def _short(response: httpx.Response) -> str:
    try:
        detail = response.json()
        message = detail.get("detail") or (detail.get("error") or {}).get("message") or ""
    except ValueError:
        message = response.text
    return str(message)[:200]


class VoyageEmbedder(_HttpEmbedder):
    provider, key_name, url = "voyage", "VOYAGE_API_KEY", VOYAGE_URL

    def _payload(self, batch: Sequence[str], input_type: InputType) -> dict:
        return {"model": self.model, "input": list(batch), "input_type": input_type}


class OpenAIEmbedder(_HttpEmbedder):
    provider, key_name, url = "openai", "OPENAI_API_KEY", OPENAI_URL

    def _payload(self, batch: Sequence[str], input_type: InputType) -> dict:  # OpenAI has no query/document distinction
        payload: dict = {"model": self.model, "input": list(batch)}
        if self.model.startswith("text-embedding-3"):
            payload["dimensions"] = self.dimension     # the -3 models can return a shortened vector
        return payload


class HashEmbedder:
    """Deterministic, network-free embeddings for tests: word-hash bag, L2 normalised."""

    provider = "fake"

    def __init__(self, dimension: int = 16, model: str = "hash", batch_size: int = 64) -> None:
        self.model, self.dimension, self.batch_size = model, dimension, batch_size
        self.calls = 0
        self.texts_embedded = 0

    def plan_batches(self, texts: Sequence[str]) -> list[list[int]]:
        return plan_batches(texts, self.batch_size, 10**9)

    def embed(self, texts: Sequence[str], input_type: InputType = "document") -> list[list[float]]:
        self.calls += 1
        self.texts_embedded += len(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for word in text.lower().split():
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def build_embedder(settings: RagSettings, client: httpx.Client | None = None) -> Embedder:
    if settings.embed_provider == "voyage":
        return VoyageEmbedder(settings.embed_model, settings.embed_dim, settings.voyage_api_key, settings.embed_batch, client,
                              max_attempts=settings.embed_max_retries, batch_tokens=settings.embed_batch_tokens)
    if settings.embed_provider == "openai":
        return OpenAIEmbedder(settings.embed_model, settings.embed_dim, settings.openai_api_key, settings.embed_batch, client,
                              max_attempts=settings.embed_max_retries, batch_tokens=settings.embed_batch_tokens)
    raise ConfigError(f"unknown embedding provider {settings.embed_provider!r}")
