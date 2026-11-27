from __future__ import annotations

import logging
from pathlib import Path

import fitz
import pytest

from app import pipeline as pipeline_module
from app.config import Settings
from app.pipeline import KonverterPipeline, _validate_remote_docling_result
from app.runpod_client import RunPodJobTimeoutError


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
        runpod_job_timeout_seconds=1800.0,
        docling_timeout_seconds=450.0,
        docling_table_mode="fast",
        docling_remote_device="cuda",
    )
    values.update(overrides)
    return Settings(**values)


def _valid_remote_payload(**overrides) -> dict:
    payload = {
        "raw_docling": {
            "pages": {"1": {"size": {"width": 595, "height": 842}}},
            "texts": [
                {
                    "self_ref": "#/texts/0",
                    "label": "text",
                    "text": "Sample paragraph.",
                    "prov": [
                        {
                            "page_no": 1,
                            "bbox": {"l": 72, "t": 100, "r": 400, "b": 120, "coord_origin": "TOPLEFT"},
                        }
                    ],
                }
            ],
        },
        "cluster_confidences": [[1, {"l": 72, "t": 100, "r": 400, "b": 120}, 0.92]],
        "doc_confidence": {
            "layout_score": 0.9,
            "mean_score": 0.9,
            "mean_grade": "good",
            "ocr_score": None,
            "table_score": None,
            "parse_score": 0.95,
            "conversion_status": "success",
            "error_count": 0,
            "failed_pages": [],
        },
        "docling_version": "2.121.0",
        "conversion_status": "success",
        "conversion_errors": [],
        "parse_elapsed_seconds": 3.5,
    }
    payload.update(overrides)
    return payload


def _make_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Sample paragraph.")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_run_docling_remote_happy_path_unique_result_key_options_and_cleanup(
    tmp_path, monkeypatch
):
    pdf_path = _make_pdf(tmp_path)
    upload_targets: list[str] = []
    submitted_payloads: list[dict] = []
    deleted_batches: list[list[str]] = []

    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "upload_pdf",
        lambda _s, doc_id, _p: f"{doc_id}/source.pdf",
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "signed_download_url",
        lambda _s, key, _ttl: f"https://signed/{key}",
    )

    def _signed_upload(_s, key, _ttl):
        upload_targets.append(key)
        return {"url": f"https://upload/{key}", "headers": {"apikey": "anon"}}

    monkeypatch.setattr(
        pipeline_module.storage_bucket, "signed_upload_target", _signed_upload
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "download_json",
        lambda _s, _key: _valid_remote_payload(),
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "delete_objects",
        lambda _s, keys, **_kw: deleted_batches.append(list(keys)) or list(keys),
    )

    def _submit(_url, _api_key, payload):
        submitted_payloads.append(payload)
        return f"job-{len(submitted_payloads)}"

    monkeypatch.setattr(pipeline_module.runpod_client, "submit", _submit)
    monkeypatch.setattr(
        pipeline_module.runpod_client,
        "poll",
        lambda _url, _api_key, _job_id, **_kw: {
            "ok": True,
            "docling_version": "2.121.0",
            "conversion_status": "success",
            "error_count": 0,
            "parse_elapsed_seconds": 3.5,
        },
    )

    pipe = KonverterPipeline(_settings())
    res1 = pipe._run_docling_remote(pdf_path, lambda *_: None, "doc-1")
    res2 = pipe._run_docling_remote(pdf_path, lambda *_: None, "doc-1")

    assert res1["docling_version"] == "2.121.0"
    assert len(upload_targets) == 2
    assert upload_targets[0] != upload_targets[1]
    assert upload_targets[0].startswith("doc-1/") and upload_targets[0].endswith("/docling.json")
    assert submitted_payloads[0]["options"] == {
        "do_ocr": False,
        "do_table_structure": True,
        "device": "cuda",
        "document_timeout": 450.0,
        "table_mode": "fast",
    }
    assert deleted_batches == [
        ["doc-1/source.pdf", upload_targets[0]],
        ["doc-1/source.pdf", upload_targets[1]],
    ]


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: RuntimeError("RunPod job job-1 failed: OOM"),
        lambda: RunPodJobTimeoutError("RunPod job job-1 did not finish within 60s"),
        lambda: InterruptedError("Processing was stopped"),
    ],
)
def test_run_docling_remote_cleans_up_on_failure_timeout_and_cancel(
    tmp_path, monkeypatch, exc_factory
):
    pdf_path = _make_pdf(tmp_path)
    deleted_batches: list[list[str]] = []
    target_keys: list[str] = []

    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "upload_pdf",
        lambda _s, doc_id, _p: f"{doc_id}/source.pdf",
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "signed_download_url",
        lambda _s, key, _ttl: f"https://signed/{key}",
    )

    def _signed_upload(_s, key, _ttl):
        target_keys.append(key)
        return {"url": f"https://upload/{key}", "headers": {}}

    monkeypatch.setattr(
        pipeline_module.storage_bucket, "signed_upload_target", _signed_upload
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "delete_objects",
        lambda _s, keys, **_kw: deleted_batches.append(list(keys)) or list(keys),
    )
    monkeypatch.setattr(pipeline_module.runpod_client, "submit", lambda *_: "job-1")

    def _poll(*_args, **_kwargs):
        raise exc_factory()

    monkeypatch.setattr(pipeline_module.runpod_client, "poll", _poll)

    pipe = KonverterPipeline(_settings())
    expected_exc = exc_factory()
    with pytest.raises(type(expected_exc)) as exc_info:
        pipe._run_docling_remote(pdf_path, lambda *_: None, "doc-9")

    assert str(expected_exc) in str(exc_info.value)
    assert deleted_batches == [["doc-9/source.pdf", target_keys[0]]]


def test_run_docling_remote_cleanup_error_never_masks_primary_error(tmp_path, monkeypatch):
    pdf_path = _make_pdf(tmp_path)

    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "upload_pdf",
        lambda _s, doc_id, _p: f"{doc_id}/source.pdf",
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "signed_download_url",
        lambda _s, key, _ttl: f"https://signed/{key}",
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "signed_upload_target",
        lambda _s, key, _ttl: {"url": f"https://upload/{key}", "headers": {}},
    )
    monkeypatch.setattr(pipeline_module.runpod_client, "submit", lambda *_: "job-1")

    def _poll(*_args, on_progress=None, **_kwargs):
        on_progress()
        return {"ok": True}

    monkeypatch.setattr(pipeline_module.runpod_client, "poll", _poll)

    def _broken_delete(*_args, **_kwargs):
        raise OSError("cleanup failed")

    monkeypatch.setattr(pipeline_module.storage_bucket, "delete_objects", _broken_delete)

    pipe = KonverterPipeline(_settings())
    with pytest.raises(InterruptedError, match="Processing was stopped"):
        pipe._run_docling_remote(
            pdf_path,
            lambda *_a: (_ for _ in ()).throw(InterruptedError("Processing was stopped")),
            "doc-cancel",
        )


def test_run_docling_remote_worker_ok_false_and_expiry_warning_and_hint(
    tmp_path, monkeypatch, caplog
):
    pdf_path = _make_pdf(tmp_path)
    deleted_batches: list[list[str]] = []

    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "upload_pdf",
        lambda _s, doc_id, _p: f"{doc_id}/source.pdf",
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "signed_download_url",
        lambda _s, key, _ttl: f"https://signed/{key}",
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "signed_upload_target",
        lambda _s, key, _ttl: {"url": f"https://upload/{key}", "headers": {}},
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "delete_objects",
        lambda _s, keys, **_kw: deleted_batches.append(list(keys)) or list(keys),
    )
    monkeypatch.setattr(pipeline_module.runpod_client, "submit", lambda *_: "job-1")
    monkeypatch.setattr(
        pipeline_module.runpod_client,
        "poll",
        lambda *_a, **_kw: {"ok": False, "error": "Result upload failed: 403 expired"},
    )

    pipe = KonverterPipeline(_settings(runpod_job_timeout_seconds=9000.0))
    with caplog.at_level(logging.WARNING, logger="konverter"):
        with pytest.raises(RuntimeError, match="Supabase signed upload URLs expire after 7200s"):
            pipe._run_docling_remote(pdf_path, lambda *_: None, "doc-exp")

    assert any("exceeds Supabase's fixed 7200s" in rec.message for rec in caplog.records)
    assert len(deleted_batches) == 1


@pytest.mark.parametrize(
    ("bad_payload", "match"),
    [
        ("not-a-dict", "expected JSON object"),
        ({"cluster_confidences": [], "doc_confidence": {}}, "raw_docling"),
        ({"raw_docling": {"pages": {}}, "cluster_confidences": [], "doc_confidence": {}}, "non-empty object"),
        ({"raw_docling": {"pages": {"1": {}}}, "cluster_confidences": {}, "doc_confidence": {}}, "cluster_confidences"),
        ({"raw_docling": {"pages": {"1": {}}}, "cluster_confidences": [], "doc_confidence": []}, "doc_confidence"),
        (_valid_remote_payload(conversion_status="failure"), "conversion_status"),
        (_valid_remote_payload(conversion_errors=["bad"]), "conversion_errors"),
        (_valid_remote_payload(docling_version=""), "docling_version"),
        (_valid_remote_payload(parse_elapsed_seconds=float("nan")), "parse_elapsed_seconds"),
        (_valid_remote_payload(parse_elapsed_seconds=True), "parse_elapsed_seconds"),
    ],
)
def test_validate_remote_docling_result_rejects_contract_mismatches(bad_payload, match):
    with pytest.raises(RuntimeError, match=match):
        _validate_remote_docling_result(bad_payload, job_id="job-bad")


def test_pipeline_process_remote_propagates_partial_success_and_version(
    tmp_path, monkeypatch
):
    pdf_path = _make_pdf(tmp_path)
    payload = _valid_remote_payload(
        docling_version="2.121.0",
        conversion_status="partial_success",
        conversion_errors=[
            {
                "component_type": "pipeline",
                "module_name": "ocr",
                "error_message": "Page 2 timed out",
                "category": "timeout",
                "page_no": 2,
            }
        ],
        parse_elapsed_seconds=12.4,
    )
    payload["doc_confidence"]["conversion_status"] = "partial_success"
    payload["doc_confidence"]["error_count"] = 1
    payload["doc_confidence"]["failed_pages"] = [2]

    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "upload_pdf",
        lambda _s, doc_id, _p: f"{doc_id}/source.pdf",
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "signed_download_url",
        lambda _s, key, _ttl: f"https://signed/{key}",
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "signed_upload_target",
        lambda _s, key, _ttl: {"url": f"https://upload/{key}", "headers": {}},
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket, "download_json", lambda _s, _k: payload
    )
    monkeypatch.setattr(
        pipeline_module.storage_bucket,
        "delete_objects",
        lambda _s, keys, **_kw: list(keys),
    )
    monkeypatch.setattr(pipeline_module.runpod_client, "submit", lambda *_: "job-1")
    monkeypatch.setattr(
        pipeline_module.runpod_client, "poll", lambda *_a, **_kw: {"ok": True}
    )

    pipe = KonverterPipeline(_settings())
    output = pipe.process(pdf_path, lambda *_: None, "doc-remote")

    assert output.docling_version == "2.121.0"
    assert output.conversion_status == "partial_success"
    assert output.parse_elapsed_seconds == 12.4
    assert len(output.conversion_errors) == 1
    assert output.doc_confidence["docling_version"] == "2.121.0"
    assert output.doc_confidence["conversion_status"] == "partial_success"
    assert output.doc_confidence["failed_pages"] == [2]
    assert any("partial_success" in w and "Page 2 timed out" in w for w in output.warnings)
