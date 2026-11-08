"""Storage: Supabase Postgres (pgvector) over PostgREST, plus an in-memory twin for tests.

Both implement the same small interface. match_chunks here mirrors the SQL function of the same
name (backend/sql/006_rag_chunks.sql): same filters, same date rule, cosine similarity.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol, Sequence

import httpx

from .models import Chunk, Link
from .settings import ConfigError, RagSettings

PAGE = 1000
log = logging.getLogger("konverter.rag.store")
_RETRY_STATUS = {408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}   # 52x: Cloudflare in front of Supabase
MAX_WAIT = 60.0


class StoreError(RuntimeError):
    """HTTP status plus a short server message; never request headers (they carry the key).
    `transient` is true when the cause looks like the link or the server (timeout, reset, 5xx), not the request."""

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class ExistingChunk:
    chunk_id: str
    content_hash: str
    row_hash: str
    embedding_model: str | None
    embedding_dim: int | None

    @property
    def fingerprint(self) -> str | None:
        return f"{self.embedding_model}:{self.embedding_dim}" if self.embedding_model else None


_F32 = struct.Struct("f")


def _float32(x: float) -> float:
    return _F32.unpack(_F32.pack(x))[0]


def _component(x: float) -> str:
    """The shortest decimal that pgvector will store as exactly float32(x).

    pgvector keeps float32. Sending 17 digits is wasteful, but so is guessing a fixed width: 7 significant
    digits would change about 69% of the stored values and 8 about 12% (a float32 needs up to 9). So convert
    to float32 first, then take the shortest string that parses back to that same float32.
    """
    if not math.isfinite(x):
        raise ValueError("embedding contains a non-finite value")
    f = _float32(float(x))
    for digits in range(1, 10):
        text = format(f, f".{digits}g")
        if _float32(float(text)) == f:
            return text
    return format(f, ".9g")


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(_component(v) for v in vector) + "]"


def chunk_row(chunk: Chunk, review_status: str) -> dict[str, Any]:
    """The non-embedding columns of rag_chunks. row_hash covers all of them, so any change to
    metadata is noticed without re-embedding, and an unchanged row is not rewritten."""
    metadata = {**chunk.metadata, "review_status": review_status}
    row = {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "version": chunk.version or "",
        "doc_type": chunk.doc_type,
        "section_id": chunk.section_id,
        "heading_path": chunk.heading_path,
        "content": chunk.text,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "source_file": chunk.source_file,
        "effective_from": chunk.effective_from,
        "effective_to": chunk.effective_to,
        "content_hash": chunk.content_hash,
        "metadata": metadata,
    }
    row["row_hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return row


def link_rows(doc_id: str, version: str, links: Iterable[Link]) -> list[dict[str, Any]]:
    return [
        {"doc_id": doc_id, "version": version or "", "from_section": l.from_section, "to_section": l.to_section,
         "kind": l.kind, "evidence": l.evidence}
        for l in links
    ]


class Store(Protocol):
    def existing_chunks(self, doc_id: str, version: str) -> dict[str, ExistingChunk]: ...
    def get_document(self, doc_id: str, version: str) -> dict[str, Any] | None: ...
    def upsert_chunks(self, rows: list[dict[str, Any]]) -> None: ...
    def delete_chunks(self, chunk_ids: list[str]) -> None: ...
    def replace_links(self, doc_id: str, version: str, rows: list[dict[str, Any]]) -> None: ...
    def upsert_document(self, row: dict[str, Any]) -> None: ...
    def known_sections(self) -> set[str]: ...
    def match_chunks(
        self, embedding: Sequence[float], k: int = 5, doc_ids: Sequence[str] | None = None,
        as_of_date: str | None = None, meta_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...
    def expand_links(
        self, seed_sections: Sequence[str], exclude_sections: Sequence[str] = (), doc_ids: Sequence[str] | None = None,
        as_of_date: str | None = None, meta_filter: dict[str, Any] | None = None, max_sections: int = 3,
    ) -> list[dict[str, Any]]: ...
    def index_status(self) -> dict[str, Any]: ...
    def index_create(self) -> dict[str, Any]: ...
    def index_drop(self) -> dict[str, Any]: ...


# --------------------------------------------------------------------------------------------

class SupabaseStore:
    def __init__(self, settings: RagSettings, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_attempts: int = 5) -> None:
        if not settings.supabase_url or not settings.supabase_key:
            raise ConfigError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        self._batch = max(1, settings.db_batch)
        self._sleep, self._attempts = sleep, max_attempts
        self._base = f"{settings.supabase_url.rstrip('/')}/rest/v1"
        self._headers = {"apikey": settings.supabase_key, "Authorization": f"Bearer {settings.supabase_key}"}
        timeout = httpx.Timeout(connect=10.0, read=settings.db_timeout, write=settings.db_timeout, pool=10.0)
        self._client = client or httpx.Client(timeout=timeout)

    def _request(self, method: str, path: str, *, params: dict | None = None, json_body: Any = None,
                 prefer: str | None = None, extra: dict[str, str] | None = None, attempts: int | None = None,
                 timeout: float | None = None) -> httpx.Response:
        headers = {**self._headers, **(extra or {}), **({"Prefer": prefer} if prefer else {})}
        # Every call here is safe to repeat: reads, deletes by key, and upserts (merge-duplicates).
        limit = attempts or self._attempts
        for attempt in range(1, limit + 1):
            try:
                response = self._client.request(method, f"{self._base}/{path}", params=params, json=json_body, headers=headers,
                                                **({"timeout": timeout} if timeout else {}))
            except httpx.TransportError as exc:               # timeouts, resets, DNS
                if attempt == limit:
                    raise StoreError(f"{method} {path}: request failed ({type(exc).__name__}) after {attempt} attempts", True) from None
                self._pause(attempt, None, f"{method} {path}: {type(exc).__name__}", limit)
                continue
            if response.status_code in _RETRY_STATUS and attempt < limit:
                self._pause(attempt, response, f"{method} {path}: HTTP {response.status_code}", limit)
                continue
            if response.status_code >= 400:
                try:
                    detail = response.json()
                    message = detail.get("message") or detail.get("hint") or ""
                except ValueError:
                    message = response.text
                tail = f" (gave up after {attempt} attempts)" if response.status_code in _RETRY_STATUS else ""
                raise StoreError(f"{method} {path}: HTTP {response.status_code}: {str(message)[:200]}{tail}",
                                 response.status_code in _RETRY_STATUS)
            return response
        raise StoreError(f"{method} {path}: gave up")  # pragma: no cover

    def _pause(self, attempt: int, response: httpx.Response | None, what: str, limit: int | None = None) -> None:
        header = response.headers.get("retry-after", "") if response is not None else ""
        wait = min(float(header), 300.0) if header.replace(".", "", 1).isdigit() else min(2.0 * 2 ** (attempt - 1), MAX_WAIT)
        log.warning("%s, retrying in %.0fs (attempt %d/%d)", what, wait, attempt, limit or self._attempts)
        self._sleep(wait)

    def _select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while True:
            page = self._request("GET", table, params={**params, "limit": str(PAGE), "offset": str(len(rows))}).json()
            rows += page
            if len(page) < PAGE:
                return rows

    def existing_chunks(self, doc_id: str, version: str) -> dict[str, ExistingChunk]:
        rows = self._select("rag_chunks", {
            "select": "chunk_id,content_hash,row_hash,embedding_model,embedding_dim",
            "doc_id": f"eq.{doc_id}", "version": f"eq.{version}", "order": "chunk_id",
        })
        return {r["chunk_id"]: ExistingChunk(r["chunk_id"], r["content_hash"], r["row_hash"],
                                             r.get("embedding_model"), r.get("embedding_dim")) for r in rows}

    def get_document(self, doc_id: str, version: str) -> dict[str, Any] | None:
        rows = self._select("rag_documents", {"select": "*", "doc_id": f"eq.{doc_id}", "version": f"eq.{version}"})
        return rows[0] if rows else None

    def upsert_chunks(self, rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), self._batch):
            self._upsert_chunks(rows[start : start + self._batch])

    def _upsert_chunks(self, rows: list[dict[str, Any]]) -> None:
        """Send a batch; if the link or server fails it twice, send two half-size requests instead of the same big one
        again (a slow upload that gets dropped at 700 KB usually gets through at 350 KB). A single row gets every retry."""
        try:
            self._request("POST", "rag_chunks", params={"on_conflict": "chunk_id"}, json_body=rows,
                          prefer="resolution=merge-duplicates,return=minimal", attempts=2 if len(rows) > 1 else None)
        except StoreError as exc:
            if not exc.transient or len(rows) == 1:
                raise
            middle = len(rows) // 2
            log.warning("splitting a failing batch of %d rows into %d + %d", len(rows), middle, len(rows) - middle)
            self._upsert_chunks(rows[:middle])
            self._upsert_chunks(rows[middle:])

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for start in range(0, len(chunk_ids), 50):
            quoted = ",".join('"' + c.replace('"', '\\"') + '"' for c in chunk_ids[start : start + 50])
            self._request("DELETE", "rag_chunks", params={"chunk_id": f"in.({quoted})"}, prefer="return=minimal")

    def replace_links(self, doc_id: str, version: str, rows: list[dict[str, Any]]) -> None:
        self._request("DELETE", "rag_links", params={"doc_id": f"eq.{doc_id}", "version": f"eq.{version}"}, prefer="return=minimal")
        for start in range(0, len(rows), self._batch):
            # An upsert, so repeating a request that actually reached the server cannot fail on the primary key.
            self._request("POST", "rag_links", params={"on_conflict": "doc_id,version,from_section,to_section,kind"},
                          json_body=rows[start : start + self._batch], prefer="resolution=merge-duplicates,return=minimal")

    def upsert_document(self, row: dict[str, Any]) -> None:
        self._request("POST", "rag_documents", params={"on_conflict": "doc_id,version"}, json_body=[row],
                      prefer="resolution=merge-duplicates,return=minimal")

    def known_sections(self) -> set[str]:
        return {r["section_id"] for r in self._select("rag_chunks", {"select": "section_id", "order": "chunk_id"})}

    def match_chunks(self, embedding, k=5, doc_ids=None, as_of_date=None, meta_filter=None):
        body = {"query_embedding": vector_literal(embedding), "k": k, "doc_ids": list(doc_ids) if doc_ids else None,
                "as_of_date": as_of_date, "meta_filter": meta_filter or {}}
        return self._request("POST", "rpc/match_chunks", json_body=body).json()

    def index_status(self) -> dict[str, Any]:
        return self._request("POST", "rpc/rag_index_status", json_body={}).json()

    def index_create(self) -> dict[str, Any]:
        # Building an index can take a while; do not retry a build that is still running on the server.
        return self._request("POST", "rpc/rag_index_create", json_body={}, attempts=1, timeout=600).json()

    def index_drop(self) -> dict[str, Any]:
        return self._request("POST", "rpc/rag_index_drop", json_body={}, attempts=1, timeout=120).json()

    def expand_links(self, seed_sections, exclude_sections=(), doc_ids=None, as_of_date=None, meta_filter=None, max_sections=3):
        body = {"seed_sections": list(seed_sections), "exclude_sections": list(exclude_sections),
                "doc_ids": list(doc_ids) if doc_ids else None, "as_of_date": as_of_date,
                "meta_filter": meta_filter or {}, "max_sections": max_sections}
        return self._request("POST", "rpc/expand_links", json_body=body).json()


# --------------------------------------------------------------------------------------------

def _in_force(row: dict[str, Any], as_of_date: str | None) -> bool:
    return not as_of_date or (
        (row.get("effective_from") is None or row["effective_from"] <= as_of_date)
        and (row.get("effective_to") is None or as_of_date < row["effective_to"])
    )


def _passes(row: dict[str, Any], doc_ids, as_of_date, meta_filter) -> bool:
    return (
        (not doc_ids or row["doc_id"] in doc_ids)
        and _in_force(row, as_of_date)
        and all(row["metadata"].get(key) == value for key, value in (meta_filter or {}).items())
    )


class MemoryStore:
    """In-memory twin of SupabaseStore. Counts writes so tests can assert "nothing was written"."""

    def __init__(self, pgvector: str = "0.8.0") -> None:
        self.pgvector, self.index_exists = pgvector, False
        self.chunks: dict[str, dict[str, Any]] = {}
        self.documents: dict[tuple[str, str], dict[str, Any]] = {}
        self.links: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.writes = 0

    def existing_chunks(self, doc_id, version):
        return {
            cid: ExistingChunk(cid, r["content_hash"], r["row_hash"], r.get("embedding_model"), r.get("embedding_dim"))
            for cid, r in self.chunks.items() if r["doc_id"] == doc_id and r["version"] == version
        }

    def get_document(self, doc_id, version):
        return self.documents.get((doc_id, version))

    def upsert_chunks(self, rows):
        for row in rows:
            self.writes += 1
            merged = {**self.chunks.get(row["chunk_id"], {}), **row}   # merge-duplicates: absent columns are kept
            self.chunks[row["chunk_id"]] = merged

    def delete_chunks(self, chunk_ids):
        for cid in chunk_ids:
            self.writes += 1
            self.chunks.pop(cid, None)

    def replace_links(self, doc_id, version, rows):
        self.writes += 1
        self.links[(doc_id, version)] = list(rows)

    def upsert_document(self, row):
        self.writes += 1
        self.documents[(row["doc_id"], row["version"])] = {**self.documents.get((row["doc_id"], row["version"]), {}), **row}

    def known_sections(self):
        return {r["section_id"] for r in self.chunks.values()}

    def match_chunks(self, embedding, k=5, doc_ids=None, as_of_date=None, meta_filter=None):
        def cosine(a: Sequence[float], b: Sequence[float]) -> float:
            na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
            return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0

        def parse(value: str | None) -> list[float]:
            return json.loads(value) if isinstance(value, str) else list(value)

        hits = []
        for row in self.chunks.values():
            if row.get("embedding") is None:
                continue
            if not _passes(row, doc_ids, as_of_date, meta_filter):
                continue
            hits.append({**{c: v for c, v in row.items() if c not in ("embedding", "row_hash", "content_hash")},
                         "similarity": cosine(parse(row["embedding"]), embedding)})
        return sorted(hits, key=lambda h: -h["similarity"])[: max(k, 0)]

    def expand_links(self, seed_sections, exclude_sections=(), doc_ids=None, as_of_date=None, meta_filter=None, max_sections=3):
        """Mirrors the SQL function of the same name."""
        seeds = list(seed_sections)
        candidates = []                      # (seed_rank, direction, kind, target, via)
        for rows in self.links.values():
            for link in rows:
                if link["from_section"] in seeds:
                    candidates.append((seeds.index(link["from_section"]), 0, link["kind"], link["to_section"], link["from_section"]))
                if link["to_section"] in seeds:
                    candidates.append((seeds.index(link["to_section"]), 1, link["kind"], link["from_section"], link["to_section"]))
        usable: dict[str, list[dict[str, Any]]] = {}
        for row in self.chunks.values():
            if _passes(row, doc_ids, as_of_date, meta_filter):
                usable.setdefault(row["section_id"], []).append(row)
        picked: dict[str, tuple] = {}
        for cand in sorted(candidates):
            target = cand[3]
            if target not in set(exclude_sections) and target in usable and target not in picked:
                picked[target] = cand
        chosen = sorted(picked.values(), key=lambda c: (c[0], c[1], c[2], c[3]))[: max(max_sections, 0)]
        out = []
        for seed_rank, _, kind, target, via in chosen:
            newest = max(r["version"] for r in usable[target])
            for row in sorted((r for r in usable[target] if r["version"] == newest), key=lambda r: r["chunk_id"]):
                out.append({**{c: v for c, v in row.items() if c not in ("embedding", "row_hash", "content_hash")},
                            "via_section": via, "link_kind": kind})
        return out

    def index_status(self):
        return {"pgvector": self.pgvector, "hnsw_supported": tuple(int(x) for x in self.pgvector.split(".")[:3]) >= (0, 8, 0),
                "index_exists": self.index_exists, "index_size": "1 MB" if self.index_exists else None,
                "chunks": len(self.chunks), "embedded_chunks": sum(1 for r in self.chunks.values() if r.get("embedding"))}

    def index_create(self):
        if not self.index_status()["hnsw_supported"]:
            raise StoreError("POST rpc/rag_index_create: HTTP 400: pgvector older than 0.8: no HNSW index created")
        self.index_exists = True
        return self.index_status()

    def index_drop(self):
        self.index_exists = False
        return self.index_status()
