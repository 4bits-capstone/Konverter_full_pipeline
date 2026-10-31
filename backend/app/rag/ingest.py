"""Ingest: PDFs (or stored structured.json) -> chunks -> embeddings -> Supabase, idempotently.

Re-running on unchanged input embeds nothing and writes nothing. A chunk is re-embedded only when
its content_hash changed or it was embedded with a different model/dimension; rows whose other
columns changed are updated without touching their embedding; chunks of vanished sections are deleted.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .chunking import ChunkReport, chunk_document
from .embeddings import Embedder, EmbeddingError
from .links import extract_links
from .models import Chunk, DocumentInfo, Link, load_manifest
from .pdftext import pdf_page_texts
from .settings import RagSettings
from .store import ExistingChunk, Store, StoreError, chunk_row, link_rows, vector_literal

log = logging.getLogger("konverter.rag.ingest")


@dataclass
class SyncResult:
    key: str
    chunks: int = 0
    embedded: int = 0
    metadata_updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    links: int = 0
    links_written: bool = False
    warnings: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (f"{self.key}: {self.chunks} chunks — embedded {self.embedded}, metadata-updated {self.metadata_updated}, "
                f"unchanged {self.unchanged}, deleted {self.deleted}; {self.links} links"
                f"{'' if self.links_written else ' (unchanged)'}")


@dataclass
class SyncPlan:
    embed: list[str]
    update_meta: list[str]
    unchanged: list[str]
    delete: list[str]


def plan_sync(existing: dict[str, ExistingChunk], rows: dict[str, dict[str, Any]], fingerprint: str) -> SyncPlan:
    """Decide what to do per chunk. `fingerprint` is "provider:model:dim" of the current embedder."""
    embed, meta, same = [], [], []
    for chunk_id, row in rows.items():
        old = existing.get(chunk_id)
        if old is None or old.content_hash != row["content_hash"] or old.fingerprint != fingerprint:
            embed.append(chunk_id)
        elif old.row_hash != row["row_hash"]:
            meta.append(chunk_id)
        else:
            same.append(chunk_id)
    return SyncPlan(embed, meta, same, sorted(set(existing) - set(rows)))


def _links_hash(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(sorted(rows, key=lambda r: json.dumps(r, sort_keys=True)), sort_keys=True).encode()).hexdigest()


def sync_document(
    info: DocumentInfo,
    chunks: list[Chunk],
    links: list[Link],
    embedder: Embedder,
    store: Store,
    settings: RagSettings,
    review_status: str,
    source_sha256: str = "",
    dry_run: bool = False,
) -> SyncResult:
    version = info.version or ""
    result = SyncResult(key=f"{info.doc_id}@{version}" if version else info.doc_id, chunks=len(chunks))
    fingerprint = f"{embedder.provider}:{embedder.model}:{embedder.dimension}"
    rows = {c.chunk_id: chunk_row(c, review_status) for c in chunks}
    plan = plan_sync(store.existing_chunks(info.doc_id, version), rows, fingerprint)
    result.embedded, result.metadata_updated = len(plan.embed), len(plan.update_meta)
    result.unchanged, result.deleted = len(plan.unchanged), len(plan.delete)

    wanted_links = link_rows(info.doc_id, version, links)
    result.links = len(wanted_links)
    previous = store.get_document(info.doc_id, version) or {}
    links_hash = _links_hash(wanted_links)
    result.links_written = previous.get("links_hash") != links_hash

    if dry_run:
        return result

    by_id = {c.chunk_id: c for c in chunks}
    stored = 0
    try:
        if plan.embed:
            # Embed a batch, write it, then the next. A failure later (rate limit, timeout) loses at most one batch:
            # everything already written is "unchanged" on the next run, so it is not embedded or paid for again.
            texts = [by_id[cid].embed_text for cid in plan.embed]
            groups = embedder.plan_batches(texts)
            for number, group in enumerate(groups, 1):
                ids = [plan.embed[index] for index in group]
                vectors = embedder.embed([texts[index] for index in group], "document")
                store.upsert_chunks([
                    {**rows[cid], "embedding": vector_literal(vec), "embedding_model": f"{embedder.provider}:{embedder.model}",
                     "embedding_dim": embedder.dimension}
                    for cid, vec in zip(ids, vectors)
                ])
                stored += len(ids)
                log.info("%s: embedded and stored batch %d/%d (%d/%d chunks)", result.key, number, len(groups), stored, len(plan.embed))
        if plan.update_meta:
            store.upsert_chunks([rows[cid] for cid in plan.update_meta])     # no embedding keys: stored vector is kept
        if result.links_written:
            store.replace_links(info.doc_id, version, wanted_links)
    except (EmbeddingError, StoreError) as exc:
        raise type(exc)(
            f"{exc} — {stored} of {len(plan.embed)} new chunks of {result.key} were stored before this; "
            f"run the same command again to continue (stored chunks are not embedded twice)"
        ) from exc
    # Only now, with every write done, remove chunks of sections that disappeared.
    if plan.delete:
        store.delete_chunks(plan.delete)

    document_row = {
        "doc_id": info.doc_id, "version": version, "doc_type": info.doc_type, "title": info.title or None,
        "publisher": info.publisher or None, "published": info.published, "law_as_at": info.law_as_at,
        "effective_from": info.effective_from_date, "effective_to": info.effective_to,
        "source_file": info.source_file or None, "source_sha256": source_sha256 or None, "review_status": review_status,
        "embedding_model": f"{embedder.provider}:{embedder.model}", "embedding_dim": embedder.dimension,
        "chunk_count": len(chunks), "links_hash": links_hash,
    }
    if any(previous.get(k) != v for k, v in document_row.items()) or plan.embed or plan.update_meta or plan.delete:
        store.upsert_document(document_row)
    return result


# --- sources ----------------------------------------------------------------------------------

@dataclass
class Source:
    key: str
    info: DocumentInfo
    structured: dict[str, Any]
    review_status: str
    pdf_pages: list[str] | None = None
    sha256: str = ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def convert_pdf(pdf: Path) -> dict[str, Any]:
    """Run the existing pipeline headlessly (no human review) and return a structured.json-shaped dict."""
    from ..config import load_settings
    from ..exporter import build_publication
    from ..pipeline import KonverterPipeline

    output = KonverterPipeline(load_settings()).process(pdf, lambda step, message: log.info("convert %s: %s", step, message), pdf.stem)
    title = (output.metadata_payload.get("metadata") or {}).get("title") or pdf.stem
    publication = build_publication(output.blocks, {"title": title})
    return {"document": {"file_name": pdf.name}, "metadata": output.metadata_payload.get("metadata", {}), "publication": publication}


def load_or_convert(pdf: Path, settings: RagSettings, reconvert: bool = False) -> tuple[dict[str, Any], str]:
    """(structured, origin). Order: <stem>.structured.json beside the PDF, the sha256 cache, then convert."""
    beside = pdf.with_suffix(".structured.json")
    if beside.is_file():
        return json.loads(beside.read_text(encoding="utf-8")), "structured.json beside the PDF"
    cache = settings.cache_dir / f"{file_sha256(pdf)}.structured.json"
    if cache.is_file() and not reconvert:
        return json.loads(cache.read_text(encoding="utf-8")), "cache"
    structured = convert_pdf(pdf)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(structured, ensure_ascii=False), encoding="utf-8")
    return structured, "converted"


def sources_from_folder(folder: Path, manifest: dict[str, DocumentInfo], settings: RagSettings,
                        only: Sequence[str] = (), reconvert: bool = False) -> tuple[list[Source], list[str]]:
    sources, warnings = [], []
    present = {p.name: p for p in folder.rglob("*.pdf")}
    for key, info in manifest.items():
        if only and key not in only and info.doc_id not in only:
            continue
        pdf = present.get(info.source_file)
        if pdf is None:
            warnings.append(f"{key}: {info.source_file or '(no file)'} not found under {folder}; skipped")
            continue
        structured, origin = load_or_convert(pdf, settings, reconvert)
        log.info("%s: structured data from %s", key, origin)
        sources.append(Source(key, info, structured, "unreviewed", pdf_page_texts(pdf), file_sha256(pdf)))
    listed = {i.source_file for i in manifest.values()}
    warnings += [f"{name}: not in the manifest; skipped" for name in sorted(present) if name not in listed]
    return sources, warnings


def source_from_store(doc_id: str, key: str, manifest: dict[str, DocumentInfo], data_dir: Path) -> Source:
    """An already processed document in the app's own store. Approved -> reviewed."""
    from ..storage import LocalDocumentStore

    store = LocalDocumentStore(data_dir)
    record = store.get_record(doc_id)
    structured = store.read_artifact(doc_id, "structured.json", None)
    status = "reviewed" if record.get("approved_at") and structured else "unreviewed"
    if structured is None:
        from ..exporter import build_publication

        structured = {"publication": build_publication(store.read_artifact(doc_id, "blocks.json", []), record)}
    pdf = store.source_path(doc_id)
    return Source(key, manifest[key], structured, status, pdf_page_texts(pdf) if pdf.is_file() else None,
                  file_sha256(pdf) if pdf.is_file() else "")


def source_from_structured(path: Path, key: str, manifest: dict[str, DocumentInfo], pdf: Path | None = None,
                           review_status: str = "unreviewed") -> Source:
    return Source(key, manifest[key], json.loads(path.read_text(encoding="utf-8")), review_status,
                  pdf_page_texts(pdf) if pdf else None, file_sha256(pdf) if pdf else "")


# --- the run ------------------------------------------------------------------------------------

def ingest(sources: Iterable[Source], embedder: Embedder, store: Store, settings: RagSettings,
           dry_run: bool = False) -> list[SyncResult]:
    chunked: list[tuple[Source, ChunkReport]] = []
    for source in sources:
        chunked.append((source, chunk_document(source.info, source.structured, settings.max_chars, source.pdf_pages)))
    known = {c.section_id for _, report in chunked for c in report.chunks} | store.known_sections()
    results = []
    for source, report in chunked:
        links = extract_links(report.chunks, known)
        result = sync_document(source.info, report.chunks, links, embedder, store, settings,
                               source.review_status, source.sha256, dry_run)
        result.warnings = list(report.warnings)
        results.append(result)
    return results
