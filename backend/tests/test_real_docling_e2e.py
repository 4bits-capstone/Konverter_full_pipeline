from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from app import docling_runner
from app.config import Settings
from app.exporter import build_json_ld, build_publication
from app.pipeline import KonverterPipeline
from app.preview_html import build_accessible_html

FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "legal_report_sample.pdf"
VALID_QUALITY_GRADES = {"poor", "fair", "good", "excellent"}


def _settings(data_dir: Path, **overrides) -> Settings:
    values = dict(
        data_dir=data_dir,
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
        docling_mode="local",
        docling_endpoint_url="",
        runpod_api_key="",
        storage_bucket="konverter-docs",
        signed_url_ttl=3600,
        supabase_url="",
        supabase_service_key="",
        docling_timeout_seconds=120.0,
        docling_table_mode="accurate",
    )
    values.update(overrides)
    return Settings(**values)


def _hf_hub_models_cached() -> bool:
    hub_cache = Path(
        os.environ.get("HF_HUB_CACHE")
        or (
            Path(os.environ["HF_HOME"]) / "hub"
            if os.environ.get("HF_HOME")
            else Path.home() / ".cache" / "huggingface" / "hub"
        )
    )
    return (
        (hub_cache / "models--docling-project--docling-layout-heron").is_dir()
        and (hub_cache / "models--docling-project--docling-models").is_dir()
    )


@pytest.fixture(scope="module", autouse=True)
def _offline_docling_env_and_cache():
    docling_runner._converter_cache.clear()
    mp = pytest.MonkeyPatch()

    # Respect HF_HUB_OFFLINE / DOCLING_ARTIFACTS_PATH when already configured (e.g. CI).
    # Locally, if HF_HUB_OFFLINE is not enabled and standard HF hub caches exist, force offline mode.
    offline_env = os.environ.get("HF_HUB_OFFLINE", "").strip().lower()
    if offline_env not in {"1", "true"} and not os.environ.get("DOCLING_ARTIFACTS_PATH"):
        if _hf_hub_models_cached():
            mp.setenv("HF_HUB_OFFLINE", "1")
            hf_constants = sys.modules.get("huggingface_hub.constants")
            if hf_constants is not None:
                mp.setattr(hf_constants, "HF_HUB_OFFLINE", True, raising=False)
    elif offline_env in {"1", "true"}:
        hf_constants = sys.modules.get("huggingface_hub.constants")
        if hf_constants is not None:
            mp.setattr(hf_constants, "HF_HUB_OFFLINE", True, raising=False)

    try:
        yield
    finally:
        mp.undo()
        docling_runner._converter_cache.clear()


def test_real_docling_runner_parses_legal_report_fixture_offline():
    assert FIXTURE_PDF.is_file(), f"Missing fixture PDF: {FIXTURE_PDF}"

    result = docling_runner.run_docling(
        FIXTURE_PDF,
        options={
            "do_ocr": False,
            "do_table_structure": True,
            "device": "cpu",
            "table_mode": "accurate",
            "document_timeout": 120.0,
        },
    )

    assert result["docling_version"] == "2.121.0"
    assert result["conversion_status"] == "success"
    assert result["conversion_errors"] == []
    assert result["parse_elapsed_seconds"] > 0

    confidence = result["doc_confidence"]
    assert confidence["mean_grade"] in VALID_QUALITY_GRADES
    assert not str(confidence["mean_grade"]).startswith("QualityGrade")
    assert confidence["conversion_status"] == "success"
    assert confidence["error_count"] == 0
    assert confidence["failed_pages"] == []

    # Strict JSON compliance (no NaN / Inf anywhere in runner result)
    json.dumps(result, allow_nan=False)

    raw_docling = result["raw_docling"]
    assert len(raw_docling["pages"]) == 6
    assert len(raw_docling["tables"]) >= 1
    assert len(raw_docling["pictures"]) >= 1

    raw_texts = raw_docling.get("texts", [])
    text_labels = {item.get("label") for item in raw_texts}
    assert "checkbox_selected" in text_labels
    assert "checkbox_unselected" in text_labels
    assert "page_header" in text_labels
    assert "page_footer" in text_labels
    assert any(
        item.get("label") == "page_header"
        and "Victorian Law Reform Commission \u00b7 Statutory Review Report"
        in str(item.get("text", ""))
        for item in raw_texts
    )
    assert any(
        item.get("label") == "page_footer"
        and "Law Reform Inquiry (2025)" in str(item.get("text", ""))
        for item in raw_texts
    )

    assert len(result["cluster_confidences"]) > 0


def test_real_docling_pipeline_to_accessible_html_e2e_offline(tmp_path: Path):
    assert FIXTURE_PDF.is_file(), f"Missing fixture PDF: {FIXTURE_PDF}"

    settings = _settings(data_dir=tmp_path / "runtime")
    stages: list[tuple[int, str]] = []
    output = KonverterPipeline(settings).process(
        FIXTURE_PDF,
        lambda step, message: stages.append((step, message)),
        "legal-report-e2e",
    )

    assert stages, "Expected KonverterPipeline to emit progress stages"
    assert output.docling_version == "2.121.0"
    assert output.conversion_status == "success"
    assert output.conversion_errors == []
    assert output.parse_elapsed_seconds is not None and output.parse_elapsed_seconds > 0
    assert output.doc_confidence["mean_grade"] in VALID_QUALITY_GRADES

    # Gap #4: raw_docling must remain unmodified Docling output (no heuristic keys, all pages & furniture intact)
    raw_serialized = json.dumps(output.raw_docling, allow_nan=False)
    assert "konverter_exclude_from_output" not in raw_serialized
    assert len(output.raw_docling["pages"]) == 6
    raw_texts = output.raw_docling.get("texts", [])
    raw_labels = {item.get("label") for item in raw_texts}
    assert "page_header" in raw_labels
    assert "page_footer" in raw_labels
    assert any(
        item.get("label") == "page_header"
        and "Victorian Law Reform Commission \u00b7 Statutory Review Report"
        in str(item.get("text", ""))
        for item in raw_texts
    )
    assert any(
        item.get("label") == "page_footer"
        and "Law Reform Inquiry (2025)" in str(item.get("text", ""))
        for item in raw_texts
    )

    # Multi-level heading hierarchy and structured content blocks
    labels = {block.get("label") for block in output.blocks}
    assert "title" in labels
    assert "table" in labels
    assert "picture" in labels
    assert "caption" in labels
    assert "footnote" in labels

    h1_texts = [
        block.get("text", "")
        for block in output.blocks
        if block.get("label") == "section_header_1"
    ]
    h2_texts = [
        block.get("text", "")
        for block in output.blocks
        if block.get("label") == "section_header_2"
    ]
    assert any("1. Introduction" in text for text in h1_texts)
    assert any("2. Statutory Framework" in text for text in h1_texts)
    assert any("1.1 Scope of Inquiry" in text for text in h2_texts)
    assert any("2.1 Recommendations" in text for text in h2_texts)

    # Running headers and footers excluded from body text blocks
    body_texts = [
        block.get("text", "")
        for block in output.blocks
        if block.get("label") == "text"
    ]
    assert not any(
        "Victorian Law Reform Commission \u00b7 Statutory Review Report" in text
        for text in body_texts
    )
    assert not any("Statutory Review Report" in text for text in body_texts)
    assert not any("Law Reform Inquiry (2025)" in text for text in body_texts)

    table_blocks = [block for block in output.blocks if block.get("label") == "table"]
    assert table_blocks and table_blocks[0].get("table_data")
    picture_blocks = [block for block in output.blocks if block.get("label") == "picture"]
    assert any(block.get("page") == 5 for block in picture_blocks)
    caption_blocks = [block for block in output.blocks if block.get("label") == "caption"]
    assert any("Figure 1:" in str(block.get("text", "")) for block in caption_blocks)
    footnote_blocks = [block for block in output.blocks if block.get("label") == "footnote"]
    assert len(footnote_blocks) >= 2

    # Build Publication -> JSON-LD -> Accessible HTML
    metadata = dict(output.metadata_payload.get("metadata") or {})
    record = {
        "title": metadata.get("title")
        or "Statutory Compliance and Administrative Review Report",
        "pages": 6,
        "file_name": FIXTURE_PDF.name,
    }
    publication = build_publication(output.blocks, record)
    assert publication["stats"]["pages"] == 6
    assert publication["stats"]["tables"] >= 1
    assert publication["stats"]["pictures"] >= 1
    assert publication["stats"]["footnotes"] >= 2

    sections = publication["sections"]
    assert len(sections) >= 2
    chapter_sections = [sec for sec in sections if sec.get("isChapter")]
    assert len(chapter_sections) >= 2
    all_section_headings = [
        str(heading.get("text", ""))
        for sec in sections
        for heading in sec.get("headings", [])
    ]
    assert any("1.1 Scope of Inquiry" in heading for heading in all_section_headings)
    assert any("2.1 Recommendations" in heading for heading in all_section_headings)

    json_ld = build_json_ld("legal-report-e2e", publication, metadata)
    accessible_html = build_accessible_html(
        "legal-report-e2e",
        publication,
        metadata,
        json_ld,
        tmp_path / "missing_cover.png",
        tmp_path / "missing_logo.png",
    )

    assert "<!doctype html>" in accessible_html.lower()
    assert "1. Introduction" in accessible_html
    assert "2. Statutory Framework" in accessible_html
    assert "<table" in accessible_html
    assert "<figure" in accessible_html
    assert "Figure 1: Statutory assessment and independent review workflow" in accessible_html

    # Strict JSON compliance across all serialized pipeline/exporter artifacts
    for artifact in (
        output.blocks,
        output.review_items,
        output.metadata_payload,
        output.raw_docling,
        output.doc_confidence,
        output.warnings,
        publication,
        json_ld,
    ):
        json.dumps(artifact, allow_nan=False)
