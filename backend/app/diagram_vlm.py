"""VLM-assisted grouping for diagram-shaped pages a purely geometric check
can't confidently split (see pipeline.py's _split_diagram_list_by_preceding_
headers, and the narrower trigger this module extends).

The model is only ever asked to decide *grouping* -- which already-extracted
item belongs under which already-extracted header -- identified by index,
never asked to read or transcribe any text itself. Docling's own extracted
text is what ends up in the document either way; this module only supplies
the index mapping between items and headers. That keeps a wrong or
low-quality page image from ever corrupting a citation, section number, or
case name -- the worst-case failure here is a wrong *grouping*, caught by
the validation below and by the review item this always creates, not
invented text.

Fails closed throughout: any missing key, network error, non-2xx response,
malformed reply, or a mapping that doesn't account for every item or leaves
a header empty returns None rather than raising, so a broken or absent API
key degrades to the existing single-merged-list-flagged-for-review
behaviour instead of interrupting document processing."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

_log = logging.getLogger(__name__)

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
_REQUEST_TIMEOUT_SECONDS = 30.0
_RENDER_DPI = 150

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _render_page_png(pdf_path: Path, page: int) -> bytes | None:
    try:
        import pymupdf
    except Exception:
        return None
    try:
        with pymupdf.open(pdf_path) as pdf:
            if not (1 <= page <= len(pdf)):
                return None
            pixmap = pdf[page - 1].get_pixmap(dpi=_RENDER_DPI)
            return pixmap.tobytes("png")
    except Exception:
        return None


def _build_prompt(headers: list[str], items: list[str]) -> str:
    header_lines = "\n".join(f"H{i}: {text}" for i, text in enumerate(headers))
    item_lines = "\n".join(f"I{i}: {text}" for i, text in enumerate(items))
    return (
        "This page contains a diagram: a short run of header labels, each "
        "visually introducing its own group of items below or beside it. "
        "Using the page image to see which items are visually grouped "
        "under which header, return ONLY a JSON array of integers, one per "
        "item below in the same order, each the index (0-based) of the "
        "header that item visually belongs to. Do not transcribe or alter "
        "any text -- the labels below are already the exact extracted "
        "text, given only so you can match them to what you see.\n\n"
        f"Headers:\n{header_lines}\n\nItems:\n{item_lines}\n\n"
        f"Output exactly {len(items)} integers in a JSON array, each "
        f"between 0 and {len(headers) - 1}. No other text."
    )


def _parse_mapping(raw_text: str, item_count: int, header_count: int) -> list[int] | None:
    cleaned = _JSON_FENCE_RE.sub("", raw_text.strip())
    try:
        mapping = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(mapping, list) or len(mapping) != item_count:
        return None
    if not all(isinstance(value, int) and 0 <= value < header_count for value in mapping):
        return None
    if len(set(mapping)) != header_count:
        # Every header must receive at least one item -- a mapping that
        # leaves one empty is exactly the "content silently dropped" shape
        # the geometric version also refuses to commit to.
        return None
    return mapping


def _call_claude_with_page_image(
    *, pdf_path: Path, page: int, prompt: str, api_key: str
) -> str | None:
    """Shared request path for every classification helper in this
    module: render the page, send it with a text prompt, return the
    model's raw text reply, or None on any failure. Never raises --
    every caller treats None as "the check could not be trusted", and
    degrades to leaving the affected content exactly as extraction left
    it, the same fail-closed behaviour whether the cause was a missing
    key, a network error, or a non-2xx response."""
    if not api_key:
        return None

    image_bytes = _render_page_png(pdf_path, page)
    if image_bytes is None:
        return None

    import base64

    image_b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    try:
        response = httpx.post(
            f"{ANTHROPIC_API_BASE}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 1024,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except httpx.HTTPError as exc:
        _log.warning("diagram_vlm: request failed: %s", exc)
        return None
    except Exception as exc:
        _log.warning("diagram_vlm: unexpected error: %s", exc)
        return None

    content = body.get("content") or []
    text_blocks = [
        block.get("text", "") for block in content if block.get("type") == "text"
    ]
    return "".join(text_blocks) if text_blocks else None


def classify_diagram_grouping(
    *,
    pdf_path: Path,
    page: int,
    headers: list[str],
    items: list[str],
    api_key: str,
) -> list[int] | None:
    """Returns a list of length len(items), each value the 0-based index
    into `headers` that item belongs under, or None if the classification
    could not be trusted."""
    if len(headers) < 2 or len(items) < len(headers):
        return None

    prompt = _build_prompt(headers, items)
    raw_text = _call_claude_with_page_image(
        pdf_path=pdf_path, page=page, prompt=prompt, api_key=api_key
    )
    if raw_text is None:
        return None

    mapping = _parse_mapping(raw_text, len(items), len(headers))
    if mapping is None:
        _log.warning("diagram_vlm: response failed validation, discarding")
    return mapping


def _build_fragment_prompt(fragments: list[str]) -> str:
    fragment_lines = "\n".join(f"I{i}: {text}" for i, text in enumerate(fragments))
    return (
        "Each numbered item below is a real, already-extracted text "
        "fragment that Docling's document-structure model placed "
        "*inside* a picture on this page (i.e. structurally nested under "
        "it, not just visually nearby). For each one, using the page "
        "image to see what it actually is, classify it as exactly one "
        "of two words:\n"
        '"diagram" -- it is a label, data point, or caption that is part '
        "of this picture's own chart/diagram/infographic content (an "
        "axis value, a legend entry, a flowchart box label, a "
        "percentage, a data-table heading fragment).\n"
        '"content" -- it is real, standalone body text that merely '
        "happens to visually sit on or near this picture (e.g. a "
        "postal address, phone number, or other text printed over a "
        "background photo or watermark).\n\n"
        "Do not transcribe or alter any text -- the labels below are "
        "already the exact extracted text, given only so you can match "
        "them to what you see.\n\n"
        f"Items:\n{fragment_lines}\n\n"
        f"Output exactly {len(fragments)} words, one per item in the "
        'same order, each either "diagram" or "content", as a JSON '
        "array of strings. No other text."
    )


def _parse_fragment_classifications(
    raw_text: str, fragment_count: int
) -> list[str] | None:
    cleaned = _JSON_FENCE_RE.sub("", raw_text.strip())
    try:
        values = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(values, list) or len(values) != fragment_count:
        return None
    normalised = [str(value).strip().lower() for value in values]
    if not all(value in ("diagram", "content") for value in normalised):
        return None
    return normalised


def classify_picture_text_fragments(
    *,
    pdf_path: Path,
    page: int,
    fragments: list[str],
    api_key: str,
) -> list[str] | None:
    """Returns a list of length len(fragments), each value either
    "diagram" (the fragment is part of the picture's own chart/diagram
    content, not independent body text) or "content" (real, standalone
    text that happens to sit on or near the picture -- e.g. a cover
    page's contact details printed over a background photo), or None if
    the classification could not be trusted.

    This never removes anything on its own -- see pipeline.py's own
    caller, which only ever uses a "diagram" classification to force the
    resulting block into human review, the same as a suspected-
    misclassified footnote or an orphaned caption, rather than excluding
    it outright. A wrong classification here risks hiding real content
    behind an unnecessary review item, never silently deleting it."""
    if len(fragments) < 2:
        return None

    prompt = _build_fragment_prompt(fragments)
    raw_text = _call_claude_with_page_image(
        pdf_path=pdf_path, page=page, prompt=prompt, api_key=api_key
    )
    if raw_text is None:
        return None

    classifications = _parse_fragment_classifications(raw_text, len(fragments))
    if classifications is None:
        _log.warning("diagram_vlm: fragment response failed validation, discarding")
    return classifications
