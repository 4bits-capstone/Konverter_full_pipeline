"""python -m app.rag <command>

  sql                          print the SQL migration with the configured embedding size
  ingest <folder>              PDFs -> chunks -> embeddings -> Supabase (idempotent)
  ingest --from-store ID --as KEY      an already processed document from the app's store
  ingest --from-structured FILE --as KEY [--pdf PDF]   stored structured.json (no Docling needed)
  ask "<question>" [--doc ID] [--as-of YYYY-MM-DD] [--links] [-k N]   answer with citations and the retrieved chunks
  index [--status|--create|--drop]   the optional HNSW index (off by default; drop it for bulk ingests, rebuild once at the end)
  n8n-export                   regenerate rag/n8n/konverter-rag-ask.json (the system prompt comes from prompts/answer_system.txt)
  eval [--questions eval/questions.csv] [--out eval/results.jsonl] [--setup NAME] [--links]   run every question through ask

Secrets come from the environment (see .env.example); they are never printed.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from .ask import ask
from .embeddings import EmbeddingError, build_embedder
from .evalrun import load_questions, run_eval, write_results
from .llm import DeepSeekClient, LLMError
from .ingest import ingest, source_from_store, source_from_structured, sources_from_folder
from .models import load_manifest
from .retrieve import RetrievalOptions
from .settings import ConfigError, load_rag_settings
from .sqlgen import render_sql
from .store import StoreError, SupabaseStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.rag", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sql = sub.add_parser("sql", help="print 006_rag_chunks.sql rendered for the embedding size")
    sql.add_argument("--dim", type=int, help="override RAG_EMBED_DIM")

    ing = sub.add_parser("ingest", help="ingest documents")
    ing.add_argument("folder", nargs="?", type=Path, help="folder holding the PDFs")
    ing.add_argument("--manifest", type=Path, help="documents.json (default: <folder>/documents.json)")
    ing.add_argument("--only", action="append", default=[], help="only this manifest key / doc_id (repeatable)")
    ing.add_argument("--reconvert", action="store_true", help="ignore the conversion cache")
    ing.add_argument("--dry-run", action="store_true", help="report what would change; write and embed nothing")
    ing.add_argument("--from-store", metavar="ID", help="document id in the app's store")
    ing.add_argument("--from-structured", metavar="FILE", type=Path, help="a structured.json file")
    ing.add_argument("--as", dest="key", help="manifest key for --from-store / --from-structured")
    ing.add_argument("--pdf", type=Path, help="source PDF for --from-structured (enables section recovery)")
    ing.add_argument("--review-status", choices=["reviewed", "unreviewed"], default="unreviewed",
                     help="for --from-structured (--from-store reads the approval state)")

    ask_p = sub.add_parser("ask", help="answer a question from the ingested documents")
    ask_p.add_argument("question")
    _retrieval_args(ask_p)
    ask_p.add_argument("--json", action="store_true", help="print the raw JSON response")

    idx = sub.add_parser("index", help="show, create or drop the optional HNSW vector index")
    mode = idx.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="show pgvector version, index and chunk counts (default)")
    mode.add_argument("--create", action="store_true", help="build the index (pgvector >= 0.8 only)")
    mode.add_argument("--drop", action="store_true", help="drop the index (before a bulk ingest)")

    sub.add_parser("n8n-export", help="regenerate rag/n8n/konverter-rag-ask.json from the template and the shared prompt")

    ev = sub.add_parser("eval", help="run questions.csv through ask")
    ev.add_argument("--questions", type=Path, default=Path("eval/questions.csv"))
    ev.add_argument("--out", type=Path, default=Path("eval/results.jsonl"))
    ev.add_argument("--setup", help="label written to every line (default: vector, or vector+links)")
    ev.add_argument("--only", action="append", default=[], help="only this question id (repeatable)")
    _retrieval_args(ev)
    return parser


def _retrieval_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--doc", action="append", default=[], help="only these doc_ids (repeatable or comma separated)")
    p.add_argument("--as-of", dest="as_of", metavar="YYYY-MM-DD", help="only text in force on this date")
    p.add_argument("--links", action="store_true", help="also add sections linked to the results (one hop, at most 3)")
    p.add_argument("-k", type=int, help="chunks to retrieve (default RAG_TOP_K)")
    p.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE", help="metadata filter, e.g. review_status=reviewed")


def _options(args: argparse.Namespace, settings) -> RetrievalOptions:
    if args.as_of and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.as_of):
        raise ValueError("--as-of must be YYYY-MM-DD")
    docs = [d.strip() for item in args.doc for d in item.split(",") if d.strip()]
    meta = dict(item.split("=", 1) for item in args.meta if "=" in item)
    if len(meta) != len(args.meta):
        raise ValueError("--meta must be KEY=VALUE")
    return RetrievalOptions(k=args.k or settings.top_k, doc_ids=docs or None, as_of_date=args.as_of, meta_filter=meta, links=args.links)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpcore"):      # one INFO line per request would drown the ingest summary
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        settings = load_rag_settings()
        if args.command == "sql":
            print(render_sql(args.dim or settings.embed_dim))
            return 0
        if args.command == "n8n-export":
            from .n8n import EXPORT, export_text

            EXPORT.write_text(export_text(), encoding="utf-8")
            print(f"wrote {EXPORT}")
            return 0
        if args.command == "index":
            return _index(args, settings)
        if args.command == "ask":
            return _ask(args, settings)
        if args.command == "eval":
            return _eval(args, settings)
        return _ingest(args, settings)
    except (ConfigError, StoreError, LLMError, EmbeddingError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


INDEX_WORTH_IT = 10_000     # chunks; below this an exact scan is fast and an HNSW index only slows writes


def _index(args: argparse.Namespace, settings) -> int:
    store = SupabaseStore(settings)
    action = "create" if args.create else "drop" if args.drop else "status"
    before = store.index_status() if action != "status" else None
    status = {"create": store.index_create, "drop": store.index_drop, "status": store.index_status}[action]()
    if before is not None:
        print(f"index {'already existed' if before['index_exists'] and action == 'create' else 'was ' + ('present' if before['index_exists'] else 'absent')}"
              f" -> {action}")
    print(f"pgvector {status['pgvector']} (HNSW {'supported' if status['hnsw_supported'] else 'not supported: needs 0.8+'})")
    print(f"HNSW index: {'present, ' + str(status['index_size']) if status['index_exists'] else 'absent (exact scan)'}")
    print(f"chunks: {status['chunks']} ({status['embedded_chunks']} embedded)")
    if action == "status":
        if status["index_exists"] and status["chunks"] < INDEX_WORTH_IT:
            print(f"hint: under {INDEX_WORTH_IT:,} chunks the index only slows writes; consider: python -m app.rag index --drop")
        elif not status["index_exists"] and status["chunks"] >= INDEX_WORTH_IT and status["hnsw_supported"]:
            print(f"hint: {status['chunks']:,} chunks; an index would speed searches: python -m app.rag index --create")
    return 0


def _ask(args: argparse.Namespace, settings) -> int:
    options = _options(args, settings)
    result, rows = ask(args.question, build_embedder(settings), SupabaseStore(settings), DeepSeekClient(settings), settings, options)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"Answer: {result['answer']}")
    print(f"Citations: {', '.join(result['citations']) or '(none)'}")
    if result["abstained"]:
        print(f"Abstained: {result.get('abstain_reason', 'yes')}" + (f" ({result['error']})" if result.get("error") else ""))
    if result["unsupported_citations"]:
        print(f"Dropped (not retrieved): {', '.join(result['unsupported_citations'])}")
    used = set(result["retrieved"])
    print(f"\nRetrieved ({len(rows)}; * = below RAG_MIN_SIMILARITY {settings.min_similarity}, not shown to the model):")
    for i, row in enumerate(rows, 1):
        sim = "link" if row.get("via_link") else f"{float(row['similarity']):.3f}"
        flag = " " if row["section_id"] in used else "*"
        pages = row.get("page_start")
        where = " > ".join(row.get("heading_path") or [])[:60]
        via = f"  [linked from {row['via_link']['from']}: {row['via_link']['kind']}]" if row.get("via_link") else ""
        print(f"{flag}{i:2}. {row['chunk_id']:<28} {sim:>6}  p.{pages}  {where}{via}")
        print(f"       {' '.join(row['content'].split())[:160]}")
    print(f"\n{result['latency_ms']} ms, model {result.get('model') or '-'}")
    return 0


def _eval(args: argparse.Namespace, settings) -> int:
    options = _options(args, settings)
    setup = args.setup or ("vector+links" if options.links else "vector")
    questions = [q for q in load_questions(args.questions) if not args.only or q["id"] in args.only]
    if not questions:
        raise ValueError("no questions to run")
    count = write_results(
        run_eval(questions, build_embedder(settings), SupabaseStore(settings), DeepSeekClient(settings), settings, options, setup),
        args.out,
    )
    print(f"{count} results -> {args.out} (setup {setup}); score with: python eval/score.py {args.out}")
    return 0


def _ingest(args: argparse.Namespace, settings) -> int:
    from_one = args.from_store or args.from_structured
    if bool(args.folder) == bool(from_one):
        raise ValueError("give either a folder, or --from-store / --from-structured with --as")
    manifest_path = args.manifest or (args.folder / "documents.json" if args.folder else None)
    if manifest_path is None:
        raise FileNotFoundError("a manifest is required: --manifest documents.json")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path.resolve()} (paths are relative to the current directory, {Path.cwd()})")
    manifest = load_manifest(manifest_path)
    warnings: list[str] = []
    if args.folder:
        sources, warnings = sources_from_folder(args.folder, manifest, settings, args.only, args.reconvert)
    else:
        if not args.key or args.key not in manifest:
            raise ValueError(f"--as must be one of: {', '.join(manifest)}")
        if args.from_store:
            from ..config import load_settings

            sources = [source_from_store(args.from_store, args.key, manifest, load_settings().data_dir)]
        else:
            sources = [source_from_structured(args.from_structured, args.key, manifest, args.pdf, args.review_status)]
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if not sources:
        print("nothing to ingest", file=sys.stderr)
        return 1
    embedder, store = build_embedder(settings), SupabaseStore(settings)
    for result in ingest(sources, embedder, store, settings, args.dry_run):
        print(("[dry run] " if args.dry_run else "") + result.line())
        if result.timing():
            print("  " + result.timing())
        for warning in result.warnings:
            print(f"  warning: {warning}", file=sys.stderr)
    print(f"embedding calls: {embedder.calls}, texts embedded: {embedder.texts_embedded} "
          f"({settings.embed_provider}/{settings.embed_model}, {settings.embed_dim} dims)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
