from __future__ import annotations

import json
from pathlib import Path

import fitz  # PyMuPDF, used only to build a real test fixture PDF
import httpx
import pytest

from app import diagram_vlm


def _write_one_page_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()


def _claude_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"content": [{"type": "text", "text": text}]},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


def test_classify_diagram_grouping_returns_none_when_api_key_missing(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    called = False

    def _fake_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("should never call the API with no key")

    monkeypatch.setattr(diagram_vlm.httpx, "post", _fake_post)

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Tier A", "Tier B"],
        items=["First", "Second"],
        api_key="",
    )

    assert result is None
    assert called is False


def test_classify_diagram_grouping_parses_a_valid_mapping(tmp_path, monkeypatch):
    """Reproduces the exact real shape validated live against the
    "Recklessness" Figure 3 page: a clean JSON array response, one index
    per item, correctly recovers the tier grouping."""
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    monkeypatch.setattr(
        diagram_vlm.httpx, "post", lambda *a, **k: _claude_response("[0, 0, 1, 1, 1]")
    )

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Tier A", "Tier B"],
        items=["a1", "a2", "b1", "b2", "b3"],
        api_key="sk-test-key",
    )

    assert result == [0, 0, 1, 1, 1]


def test_classify_diagram_grouping_strips_markdown_fences(tmp_path, monkeypatch):
    """Claude commonly wraps JSON answers in a ```json fence even when
    asked for JSON only -- the real live test output during development
    came back this way."""
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    monkeypatch.setattr(
        diagram_vlm.httpx,
        "post",
        lambda *a, **k: _claude_response("```json\n[1, 0]\n```"),
    )

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Tier A", "Tier B"],
        items=["a1", "a2"],
        api_key="sk-test-key",
    )

    assert result == [1, 0]


def test_classify_diagram_grouping_rejects_a_mapping_that_leaves_a_header_empty(
    tmp_path, monkeypatch
):
    """The same content-safety invariant as the geometric split: a
    mapping that never assigns anything to one header would silently
    drop that tier's items out of the document if trusted, so it must be
    rejected rather than applied."""
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    monkeypatch.setattr(
        diagram_vlm.httpx, "post", lambda *a, **k: _claude_response("[0, 0, 0]")
    )

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Tier A", "Tier B"],
        items=["a1", "a2", "a3"],
        api_key="sk-test-key",
    )

    assert result is None


def test_classify_diagram_grouping_rejects_malformed_json(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    monkeypatch.setattr(
        diagram_vlm.httpx,
        "post",
        lambda *a, **k: _claude_response("I'm not sure, sorry!"),
    )

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Tier A", "Tier B"],
        items=["a1", "a2"],
        api_key="sk-test-key",
    )

    assert result is None


def test_classify_diagram_grouping_rejects_wrong_length_mapping(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    monkeypatch.setattr(
        diagram_vlm.httpx, "post", lambda *a, **k: _claude_response("[0, 1]")
    )

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Tier A", "Tier B"],
        items=["a1", "a2", "a3"],
        api_key="sk-test-key",
    )

    assert result is None


def test_classify_diagram_grouping_fails_closed_on_http_error(tmp_path, monkeypatch):
    """A network error, timeout, or non-2xx response must never raise up
    into the pipeline -- document processing has to keep going with the
    page simply flagged for human review instead."""
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    def _raise(*args, **kwargs):
        raise httpx.ConnectTimeout("boom")

    monkeypatch.setattr(diagram_vlm.httpx, "post", _raise)

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Tier A", "Tier B"],
        items=["a1", "a2"],
        api_key="sk-test-key",
    )

    assert result is None


def test_classify_diagram_grouping_fails_closed_on_non_2xx_status(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    def _fake_post(*args, **kwargs):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        return httpx.Response(401, json={"error": "unauthorized"}, request=request)

    monkeypatch.setattr(diagram_vlm.httpx, "post", _fake_post)

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Tier A", "Tier B"],
        items=["a1", "a2"],
        api_key="sk-bad-key",
    )

    assert result is None


def test_classify_diagram_grouping_requires_at_least_two_headers(tmp_path, monkeypatch):
    """A single trailing header is the overwhelmingly common, correct
    shape (an ordinary heading followed by its own list) -- never worth
    an API call, let alone a split."""
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    called = False

    def _fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return _claude_response("[0]")

    monkeypatch.setattr(diagram_vlm.httpx, "post", _fake_post)

    result = diagram_vlm.classify_diagram_grouping(
        pdf_path=pdf_path,
        page=1,
        headers=["Only one header"],
        items=["a1"],
        api_key="sk-test-key",
    )

    assert result is None
    assert called is False


def test_render_page_png_returns_none_for_an_out_of_range_page(tmp_path):
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    assert diagram_vlm._render_page_png(pdf_path, 5) is None


def test_classify_picture_text_fragments_parses_a_valid_response(tmp_path, monkeypatch):
    """Reproduces the real shape found live in "Review of the Bail Act":
    a data table's legend fragmented across separate blocks ("Per",
    "centage of", "To", "tal") alongside real, unrelated body text --
    the model correctly tells which fragments are the table's own
    internal labelling apart from genuine standalone content."""
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    monkeypatch.setattr(
        diagram_vlm.httpx,
        "post",
        lambda *a, **k: _claude_response('["diagram", "diagram", "content"]'),
    )

    result = diagram_vlm.classify_picture_text_fragments(
        pdf_path=pdf_path,
        page=1,
        fragments=["Per", "centage of", "1300 666 555 (within Victoria)"],
        api_key="sk-test-key",
    )

    assert result == ["diagram", "diagram", "content"]


def test_classify_picture_text_fragments_requires_at_least_two_fragments(tmp_path):
    """A single text fragment nested under a picture could easily be a
    genuine caption -- not worth an API call, let alone a classification,
    the same reasoning the diagram-grouping check applies to a single
    trailing header."""
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    result = diagram_vlm.classify_picture_text_fragments(
        pdf_path=pdf_path, page=1, fragments=["Only one"], api_key="sk-test-key"
    )

    assert result is None


def test_classify_picture_text_fragments_rejects_an_invalid_label(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    monkeypatch.setattr(
        diagram_vlm.httpx,
        "post",
        lambda *a, **k: _claude_response('["diagram", "maybe"]'),
    )

    result = diagram_vlm.classify_picture_text_fragments(
        pdf_path=pdf_path,
        page=1,
        fragments=["a", "b"],
        api_key="sk-test-key",
    )

    assert result is None


def test_classify_picture_text_fragments_rejects_wrong_length(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    monkeypatch.setattr(
        diagram_vlm.httpx, "post", lambda *a, **k: _claude_response('["diagram"]')
    )

    result = diagram_vlm.classify_picture_text_fragments(
        pdf_path=pdf_path,
        page=1,
        fragments=["a", "b"],
        api_key="sk-test-key",
    )

    assert result is None


def test_classify_picture_text_fragments_fails_closed_without_an_api_key(tmp_path, monkeypatch):
    called = False

    def _fake_post(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(diagram_vlm.httpx, "post", _fake_post)
    pdf_path = tmp_path / "source.pdf"
    _write_one_page_pdf(pdf_path)

    result = diagram_vlm.classify_picture_text_fragments(
        pdf_path=pdf_path, page=1, fragments=["a", "b"], api_key=""
    )

    assert result is None
    assert called is False
