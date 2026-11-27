from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


HANDLER_PATH = (
    Path(__file__).resolve().parents[2] / "docling_worker" / "handler.py"
)


class _FakeResponse:
    def __init__(self, *, chunks=None, exc: Exception | None = None):
        self._chunks = chunks or []
        self._exc = exc

    def raise_for_status(self) -> None:
        if self._exc is not None:
            raise self._exc

    def iter_content(self, chunk_size: int = 1024):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _load_handler(monkeypatch, *, run_docling_impl=None, fake_requests=None):
    start_calls: list[dict] = []

    fake_runpod = types.ModuleType("runpod")
    fake_runpod.serverless = types.SimpleNamespace(start=start_calls.append)

    if fake_requests is None:
        fake_requests = types.SimpleNamespace(
            get=lambda *a, **kw: _FakeResponse(chunks=[b"%PDF-1.4\n"]),
            put=lambda *a, **kw: _FakeResponse(),
        )

    if run_docling_impl is None:
        run_docling_impl = lambda pdf_path, options: {
            "raw_docling": {"pages": {"1": {}}},
            "cluster_confidences": [],
            "doc_confidence": {"mean_grade": "good"},
            "docling_version": "2.121.0",
            "conversion_status": "success",
            "conversion_errors": [],
            "parse_elapsed_seconds": 1.25,
        }

    fake_docling_runner = types.ModuleType("docling_runner")
    fake_docling_runner.run_docling = run_docling_impl

    monkeypatch.setitem(sys.modules, "runpod", fake_runpod)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setitem(sys.modules, "docling_runner", fake_docling_runner)

    spec = importlib.util.spec_from_file_location("docling_worker_handler", HANDLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, start_calls


def test_import_does_not_start_runpod_serverless(monkeypatch):
    module, start_calls = _load_handler(monkeypatch)
    assert callable(module.handler)
    assert start_calls == []


def test_handler_downloads_runs_docling_uploads_full_payload_and_returns_metadata(
    monkeypatch,
):
    recorded: dict[str, object] = {}
    expected_payload = {
        "raw_docling": {"pages": {"1": {"size": {"width": 612, "height": 792}}}},
        "cluster_confidences": [[1, {"l": 0.0, "t": 0.0, "r": 10.0, "b": 10.0}, 0.9]],
        "doc_confidence": {
            "mean_grade": "good",
            "conversion_status": "partial_success",
            "error_count": 1,
            "failed_pages": [2],
        },
        "docling_version": "2.121.0",
        "conversion_status": "partial_success",
        "conversion_errors": [
            {
                "component_type": "model",
                "module_name": "tableformer",
                "error_message": "timeout on page 2",
                "category": "timeout",
                "page_no": 2,
            }
        ],
        "parse_elapsed_seconds": 3.45,
    }

    def fake_get(url, stream=False, timeout=None):
        recorded["get_url"] = url
        recorded["get_stream"] = stream
        return _FakeResponse(chunks=[b"%PDF-1.4\n", b"body"])

    def fake_put(url, data=None, headers=None, timeout=None):
        recorded["put_url"] = url
        recorded["put_headers"] = headers
        recorded["put_body"] = json.loads(data.read().decode("utf-8"))
        return _FakeResponse()

    def fake_run_docling(pdf_path, options):
        recorded["pdf_bytes"] = Path(pdf_path).read_bytes()
        recorded["options"] = options
        return expected_payload

    module, _ = _load_handler(
        monkeypatch,
        run_docling_impl=fake_run_docling,
        fake_requests=types.SimpleNamespace(get=fake_get, put=fake_put),
    )

    options = {
        "do_ocr": False,
        "do_table_structure": True,
        "device": "cuda",
        "document_timeout": 600.0,
        "table_mode": "accurate",
    }
    result = module.handler(
        {
            "input": {
                "pdf_download_url": "https://storage.example/source.pdf?token=abc",
                "result_upload": {
                    "url": "https://storage.example/upload/docling.json?token=xyz",
                    "headers": {
                        "apikey": "anon-key",
                        "Authorization": "Bearer anon-key",
                    },
                },
                "options": options,
            }
        }
    )

    assert recorded["get_url"] == "https://storage.example/source.pdf?token=abc"
    assert recorded["get_stream"] is True
    assert recorded["pdf_bytes"] == b"%PDF-1.4\nbody"
    assert recorded["options"] == options
    assert (
        recorded["put_url"] == "https://storage.example/upload/docling.json?token=xyz"
    )
    assert recorded["put_headers"] == {
        "content-type": "application/json",
        "apikey": "anon-key",
        "Authorization": "Bearer anon-key",
    }
    assert recorded["put_body"] == expected_payload
    assert result == {
        "ok": True,
        "docling_version": "2.121.0",
        "conversion_status": "partial_success",
        "error_count": 1,
        "parse_elapsed_seconds": 3.45,
    }


def test_handler_handles_null_options_and_signed_url_fallback(monkeypatch):
    recorded: dict[str, object] = {}

    def fake_put(url, data=None, headers=None, timeout=None):
        recorded["put_url"] = url
        return _FakeResponse()

    def fake_run_docling(pdf_path, options):
        recorded["options"] = options
        return {
            "raw_docling": {"pages": {"1": {}}},
            "cluster_confidences": [],
            "doc_confidence": {},
            "docling_version": "2.121.0",
            "conversion_status": "success",
            "conversion_errors": [],
            "parse_elapsed_seconds": 0.5,
        }

    module, _ = _load_handler(
        monkeypatch,
        run_docling_impl=fake_run_docling,
        fake_requests=types.SimpleNamespace(
            get=lambda *a, **kw: _FakeResponse(chunks=[b"%PDF-1.4\n"]),
            put=fake_put,
        ),
    )

    result = module.handler(
        {
            "input": {
                "pdf_download_url": "https://storage.example/source.pdf",
                "result_upload": {"signed_url": "https://storage.example/signed"},
                "options": None,
            }
        }
    )

    assert recorded["options"] == {}
    assert recorded["put_url"] == "https://storage.example/signed"
    assert result["ok"] is True


def test_handler_propagates_download_runner_and_upload_errors(monkeypatch):
    base_job = {
        "input": {
            "pdf_download_url": "https://storage.example/source.pdf",
            "result_upload": {"url": "https://storage.example/upload"},
            "options": {},
        }
    }

    # 1. Download HTTP error
    mod_dl, _ = _load_handler(
        monkeypatch,
        fake_requests=types.SimpleNamespace(
            get=lambda *a, **kw: _FakeResponse(exc=RuntimeError("403 forbidden")),
            put=lambda *a, **kw: _FakeResponse(),
        ),
    )
    with pytest.raises(RuntimeError, match="403 forbidden"):
        mod_dl.handler(base_job)

    # 2. Runner failure
    mod_run, _ = _load_handler(
        monkeypatch,
        run_docling_impl=lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("Docling conversion failed")
        ),
    )
    with pytest.raises(RuntimeError, match="Docling conversion failed"):
        mod_run.handler(base_job)

    # 3. Upload HTTP error
    mod_up, _ = _load_handler(
        monkeypatch,
        fake_requests=types.SimpleNamespace(
            get=lambda *a, **kw: _FakeResponse(chunks=[b"%PDF-1.4\n"]),
            put=lambda *a, **kw: _FakeResponse(exc=RuntimeError("502 bad gateway")),
        ),
    )
    with pytest.raises(RuntimeError, match="502 bad gateway"):
        mod_up.handler(base_job)
