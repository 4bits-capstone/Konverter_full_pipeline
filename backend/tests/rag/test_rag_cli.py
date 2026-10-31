from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.rag import cli
from app.rag.embeddings import HashEmbedder
from app.rag.store import MemoryStore

FIXTURES = Path(__file__).parent / "fixtures"
SECRET = "super-secret-key-value-9999"


def test_sql_command_prints_the_rendered_migration(capsys, monkeypatch):
    monkeypatch.setenv("RAG_EMBED_DIM", "1024")
    assert cli.main(["sql"]) == 0
    assert "vector(1024)" in capsys.readouterr().out
    assert cli.main(["sql", "--dim", "8"]) == 0 and "vector(8)" in capsys.readouterr().out


def test_bad_configuration_is_an_error_message_not_a_traceback(capsys, monkeypatch):
    monkeypatch.setenv("RAG_EMBED_DIM", "99999")
    assert cli.main(["sql"]) == 2
    assert "RAG_EMBED_DIM" in capsys.readouterr().err


def test_ingest_from_structured_end_to_end_and_never_prints_secrets(capsys, monkeypatch):
    for name in ("VOYAGE_API_KEY", "SUPABASE_SERVICE_ROLE_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, SECRET)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    store, embedder = MemoryStore(), HashEmbedder(16)
    monkeypatch.setattr(cli, "build_embedder", lambda settings: embedder)
    monkeypatch.setattr(cli, "SupabaseStore", lambda settings: store)
    args = ["ingest", "--from-structured", str(FIXTURES / "report.json"), "--as", "report",
            "--manifest", str(FIXTURES / "documents.json"), "--review-status", "reviewed"]
    assert cli.main(args) == 0
    first = capsys.readouterr()
    assert "report:" in first.out and "embedded" in first.out
    assert store.chunks and all(r["metadata"]["review_status"] == "reviewed" for r in store.chunks.values())
    embedded_first = embedder.texts_embedded
    assert embedded_first == len(store.chunks)
    assert cli.main(args) == 0
    second = capsys.readouterr()
    assert "embedded 0" in second.out and embedder.texts_embedded == embedded_first
    assert SECRET not in first.out + first.err + second.out + second.err


def test_dry_run_flag(capsys, monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(cli, "build_embedder", lambda settings: HashEmbedder(16))
    monkeypatch.setattr(cli, "SupabaseStore", lambda settings: store)
    assert cli.main(["ingest", "--from-structured", str(FIXTURES / "paper.json"), "--as", "paper",
                     "--manifest", str(FIXTURES / "documents.json"), "--dry-run"]) == 0
    assert "[dry run]" in capsys.readouterr().out and store.writes == 0


def test_folder_ingest_skips_files_without_a_manifest_entry_and_reports_missing_pdfs(tmp_path, capsys, monkeypatch):
    (tmp_path / "unlisted.pdf").write_bytes(b"%PDF")
    (tmp_path / "documents.json").write_text(json.dumps({"documents": [
        {"doc_id": "x", "doc_type": "report", "title": "X", "file": "raw/missing.pdf", "published": "2020-01-01"}]}))
    monkeypatch.setattr(cli, "build_embedder", lambda settings: HashEmbedder(16))
    monkeypatch.setattr(cli, "SupabaseStore", lambda settings: MemoryStore())
    assert cli.main(["ingest", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "missing.pdf not found" in err and "unlisted.pdf: not in the manifest" in err


@pytest.mark.parametrize("argv,message", [
    (["ingest"], "either a folder"),
    (["ingest", "--from-structured", "x.json"], "manifest is required"),
])
def test_argument_errors(argv, message, capsys):
    assert cli.main(argv) == 2
    assert message in capsys.readouterr().err
