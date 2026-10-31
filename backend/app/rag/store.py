"""Storage: Supabase Postgres (pgvector) over PostgREST, plus an in-memory twin for tests.

Both implement the same small interface. match_chunks here mirrors the SQL function of the same
name (backend/sql/006_rag_chunks.sql): same filters, same date rule, cosine similarity.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence

import httpx

from .models import Chunk, Link
from .settings import ConfigError, RagSettings

PAGE = 1000


class StoreError(RuntimeError):
    """HTTP status plus a short server message; never request headers (they carry the key)."""


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


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


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


# --------------------------------------------------------------------------------------------

class SupabaseStore:
    def __init__(self, settings: RagSettings, client: httpx.Client | None = None) -> None:
        if not settings.supabase_url or not settings.supabase_key:
            raise ConfigError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        self._base = f"{settings.supabase_url.rstrip('/')}/rest/v1"
        self._headers = {"apikey": settings.supabase_key, "Authorization": f"Bearer {settings.supabase_key}"}
        self._client = client or httpx.Client(timeout=60)

    def _request(self, method: str, path: str, *, params: dict | None = None, json_body: Any = None,
                 prefer: str | None = None, extra: dict[str, str] | None = None) -> httpx.Response:
        headers = {**self._headers, **(extra or {}), **({"Prefer": prefer} if prefer else {})}
        try:
            response = self._client.request(method, f"{self._base}/{path}", params=params, json=json_body, headers=headers)
        except httpx.HTTPError as exc:
            raise StoreError(f"{method} {path}: request failed ({type(exc).__name__})") from None
        if response.status_code >= 400:
            try:
                detail = response.json()
                message = detail.get("message") or detail.get("hint") or ""
            except ValueError:
                message = response.text
            raise StoreError(f"{method} {path}: HTTP {response.status_code}: {str(message)[:200]}")
        return response

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
        for start in range(0, len(rows), 100):
            self._request("POST", "rag_chunks", params={"on_conflict": "chunk_id"}, json_body=rows[start : start + 100],
                          prefer="resolution=merge-duplicates,return=minimal")

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for start in range(0, len(chunk_ids), 50):
            quoted = ",".join('"' + c.replace('"', '\\"') + '"' for c in chunk_ids[start : start + 50])
            self._request("DELETE", "rag_chunks", params={"chunk_id": f"in.({quoted})"}, prefer="return=minimal")

    def replace_links(self, doc_id: str, version: str, rows: list[dict[str, Any]]) -> None:
        self._request("DELETE", "rag_links", params={"doc_id": f"eq.{doc_id}", "version": f"eq.{version}"}, prefer="return=minimal")
        for start in range(0, len(rows), 200):
            self._request("POST", "rag_links", json_body=rows[start : start + 200], prefer="return=minimal")

    def upsert_document(self, row: dict[str, Any]) -> None:
        self._request("POST", "rag_documents", params={"on_conflict": "doc_id,version"}, json_body=[row],
                      prefer="resolution=merge-duplicates,return=minimal")

    def known_sections(self) -> set[str]:
        return {r["section_id"] for r in self._select("rag_chunks", {"select": "section_id", "order": "chunk_id"})}

    def match_chunks(self, embedding, k=5, doc_ids=None, as_of_date=None, meta_filter=None):
        body = {"query_embedding": vector_literal(embedding), "k": k, "doc_ids": list(doc_ids) if doc_ids else None,
                "as_of_date": as_of_date, "meta_filter": meta_filter or {}}
        return self._request("POST", "rpc/match_chunks", json_body=body).json()

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

    def __init__(self) -> None:
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
