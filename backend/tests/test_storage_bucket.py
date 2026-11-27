from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

import pytest

from app import storage_bucket
from app.config import Settings


def _settings(**overrides) -> Settings:
    values = dict(
        data_dir=Path("/tmp/konverter-test"),
        cors_origins=("http://localhost:5173",),
        do_ocr=False,
        do_table_structure=True,
        docling_device="cpu",
        worker_count=1,
        max_pages=2000,
        high_confidence_threshold=0.75,
        medium_confidence_threshold=0.60,
        baseline_seconds_per_page=2.8,
        baseline_startup_seconds=30.0,
        site_url="",
        site_name="",
        page_url_template="",
        public_api_url="",
        default_license_url="",
        default_copyright_holder="",
        description_max_chars=600,
        log_level="INFO",
        openai_api_key="",
        claude_api_key="",
        docling_mode="remote",
        docling_endpoint_url="https://api.runpod.ai/v2/test",
        runpod_api_key="rp-key",
        storage_bucket="konverter-docs",
        signed_url_ttl=3600,
        supabase_url="https://example.supabase.co",
        supabase_service_key="service-role-key",
    )
    values.update(overrides)
    return Settings(**values)


class _FakeBucket:
    def __init__(self, tree: dict[str, list[dict]] | None = None) -> None:
        self.tree = tree or {}
        self.list_calls: list[tuple[str, dict]] = []
        self.remove_calls: list[list[str]] = []
        self.upload_url_calls: list[tuple[str, object]] = []
        self.fail_list: Exception | None = None
        self.fail_remove_batches: set[int] = set()
        self.fail_upload_url: Exception | None = None

    def list(self, prefix: str | None = None, options: dict | None = None):
        self.list_calls.append((prefix or "", dict(options or {})))
        if self.fail_list is not None:
            raise self.fail_list
        entries = self.tree.get(prefix or "", [])
        offset = int((options or {}).get("offset", 0))
        limit = int((options or {}).get("limit", 100))
        return entries[offset : offset + limit]

    def remove(self, paths: list[str]):
        batch_index = len(self.remove_calls)
        self.remove_calls.append(list(paths))
        if batch_index in self.fail_remove_batches:
            raise RuntimeError(f"simulated remove failure on batch {batch_index}")
        return [{"name": p} for p in paths]

    def create_signed_upload_url(self, object_key: str, options: object = None):
        self.upload_url_calls.append((object_key, options))
        if self.fail_upload_url is not None:
            raise self.fail_upload_url
        return {"signed_url": f"https://example.supabase.co/upload/{object_key}?token=abc"}


def test_is_configured_checks_url_key_and_bucket():
    assert storage_bucket.is_configured(_settings()) is True
    assert storage_bucket.is_configured(_settings(supabase_url="  ")) is False
    assert storage_bucket.is_configured(_settings(supabase_service_key="")) is False
    assert storage_bucket.is_configured(_settings(storage_bucket="")) is False


def test_delete_objects_noop_when_unconfigured_or_empty(monkeypatch):
    called = False

    def _fail_bucket(_settings):
        nonlocal called
        called = True
        return _FakeBucket()

    monkeypatch.setattr(storage_bucket, "_bucket", _fail_bucket)

    assert storage_bucket.delete_objects(_settings(supabase_url=""), ["doc/source.pdf"]) == []
    assert storage_bucket.delete_objects(_settings(), ["", "   ", "/"]) == []
    assert called is False


def test_delete_objects_deduplicates_strips_and_batches_by_1000(monkeypatch):
    bucket = _FakeBucket()
    monkeypatch.setattr(storage_bucket, "_bucket", lambda _s: bucket)

    keys = [f"/doc1/file-{i}.json" for i in range(2050)]
    keys.insert(5, "doc1/file-0.json")  # duplicate

    removed = storage_bucket.delete_objects(_settings(), keys)

    assert len(removed) == 2050
    assert removed[0] == "doc1/file-0.json"
    assert [len(call) for call in bucket.remove_calls] == [1000, 1000, 50]


def test_delete_objects_logs_and_swallows_unless_raise_on_error(monkeypatch, caplog):
    bucket = _FakeBucket()
    bucket.fail_remove_batches.add(0)
    monkeypatch.setattr(storage_bucket, "_bucket", lambda _s: bucket)

    keys = [f"doc1/a-{i}.json" for i in range(1005)]
    with caplog.at_level(logging.WARNING, logger="konverter.storage_bucket"):
        removed = storage_bucket.delete_objects(_settings(), keys, raise_on_error=False)

    assert len(removed) == 5
    assert removed[0] == "doc1/a-1000.json"
    assert any("Failed to delete 1000 remote storage object(s)" in rec.message for rec in caplog.records)

    bucket_strict = _FakeBucket()
    bucket_strict.fail_remove_batches.add(0)
    monkeypatch.setattr(storage_bucket, "_bucket", lambda _s: bucket_strict)

    with pytest.raises(RuntimeError, match="simulated remove failure"):
        storage_bucket.delete_objects(_settings(), ["doc1/source.pdf"], raise_on_error=True)


def test_delete_document_objects_walks_nested_folders_and_paginates(monkeypatch):
    first_page_files = [
        {"name": f"part-{i:03d}.json", "id": f"uuid-{i}", "metadata": {"size": 10}}
        for i in range(99)
    ]
    first_page_files.append({"name": "attempt-1", "id": None, "metadata": None})
    second_page_files = [
        {"name": "source.pdf", "id": "uuid-src", "metadata": {"size": 123}},
        {"name": "attempt-2", "metadata": None},  # folder without id key
    ]
    bucket = _FakeBucket(
        tree={
            "doc-42": first_page_files + second_page_files,
            "doc-42/attempt-1": [
                {"name": "docling.json", "id": "uuid-d1", "metadata": {"size": 50}},
            ],
            "doc-42/attempt-2": [
                {"name": "docling.json", "id": "uuid-d2", "metadata": {"size": 60}},
            ],
        }
    )
    monkeypatch.setattr(storage_bucket, "_bucket", lambda _s: bucket)

    deleted_count = storage_bucket.delete_document_objects(_settings(), "/doc-42/")

    assert deleted_count == 102
    removed_all = [path for call in bucket.remove_calls for path in call]
    assert "doc-42/source.pdf" in removed_all
    assert "doc-42/attempt-1/docling.json" in removed_all
    assert "doc-42/attempt-2/docling.json" in removed_all
    assert [opts["offset"] for prefix, opts in bucket.list_calls if prefix == "doc-42"] == [0, 100]


def test_delete_document_objects_returns_zero_when_unconfigured_or_list_fails(
    monkeypatch, caplog
):
    assert storage_bucket.delete_document_objects(_settings(supabase_url=""), "doc-1") == 0
    assert storage_bucket.delete_document_objects(_settings(), "   ") == 0

    bucket = _FakeBucket()
    bucket.fail_list = RuntimeError("storage outage")
    monkeypatch.setattr(storage_bucket, "_bucket", lambda _s: bucket)

    with caplog.at_level(logging.WARNING, logger="konverter.storage_bucket"):
        count = storage_bucket.delete_document_objects(_settings(), "doc-1")

    assert count == 0
    assert any("Failed to list remote storage objects" in rec.message for rec in caplog.records)


def test_signed_upload_target_warns_above_fixed_ttl_and_wraps_errors(monkeypatch, caplog):
    fake_storage3 = types.ModuleType("storage3")
    fake_types = types.ModuleType("storage3.types")

    class _FakeOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_types.CreateSignedUploadUrlOptions = _FakeOptions
    fake_storage3.types = fake_types
    monkeypatch.setitem(sys.modules, "storage3", fake_storage3)
    monkeypatch.setitem(sys.modules, "storage3.types", fake_types)

    bucket = _FakeBucket()
    monkeypatch.setattr(storage_bucket, "_bucket", lambda _s: bucket)

    with caplog.at_level(logging.WARNING, logger="konverter.storage_bucket"):
        target = storage_bucket.signed_upload_target(
            _settings(), "doc-1/abc/docling.json", ttl=9000
        )

    assert target["url"].endswith("doc-1/abc/docling.json?token=abc")
    assert "apikey" in target["headers"]
    assert any("exceeds Supabase's fixed 7200s" in rec.message for rec in caplog.records)

    bucket.fail_upload_url = ValueError("403 forbidden")
    with pytest.raises(RuntimeError, match="Failed to create signed upload URL"):
        storage_bucket.signed_upload_target(_settings(), "doc-1/abc/docling.json", ttl=3600)
