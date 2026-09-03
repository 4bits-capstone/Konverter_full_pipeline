"""Document chat assistant: builds a bounded context from a document's
structured.json + schema.jsonld exports, then streams a chat completion and
text-to-speech audio from the OpenAI REST API via httpx (no SDK dependency,
consistent with the rest of this backend's httpx-based footprint)."""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

import httpx

from .config import Settings

OPENAI_API_BASE = "https://api.openai.com/v1"
CHAT_MODEL = "gpt-4o-mini"
TTS_MODEL = "tts-1"
TTS_VOICE = "nova"

# Keeps every chat turn's cost/latency bounded regardless of document length,
# instead of forwarding the full block tree (which can be very large). Most
# reports fit under this whole, in document order (see build_chat_context);
# only documents that don't need the relevance-ranked fallback below.
CHAT_CONTEXT_CHAR_BUDGET = 60_000

_WORD_RE = re.compile(r"[a-z0-9]+")

# Common English words excluded from relevance scoring so they don't drown
# out the topical words a question is actually about.
_STOPWORDS = frozenset(
    """
    a an the this that these those is are was were be been being do does did
    of to in on at by for with about against between into through during
    before after above below from up down out off over under again further
    and or but if then else when where why how all any both each few more
    most other some such no nor not only own same so than too very can will
    just should now what which who whom it its i you he she we they them
    their our your his her my me us as
    """.split()
)


def _keywords(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall(text.lower()) if word not in _STOPWORDS and len(word) > 2}

SYSTEM_PROMPT_TEMPLATE = (
    "You are a helpful assistant answering questions about a single "
    "reviewed document for its publisher. For questions about the "
    "document's content, answer only using the document context below; "
    "don't guess or add details that aren't there. When you can't answer, "
    "don't just say \"I don't know\" — say so in a way that helps the "
    "reader move forward: "
    "- If the question asks for your own opinion, judgment, or a "
    "\"verdict\" rather than what the document itself says, explain that "
    "you don't offer opinions, and offer instead to summarize the "
    "document's own findings, conclusions, or recommendations. "
    "- If the topic genuinely isn't covered in the context you were "
    "given, say that plainly and suggest a more specific way to ask (a "
    "chapter or topic name) or point to what you can help with instead, "
    "such as its key findings, recommendations, or a summary. "
    "Greetings, thanks, and other small talk aren't document "
    "questions — respond to those naturally and briefly, the way a "
    "helpful assistant would, without saying you don't know. Keep "
    "answers concise.\n\n"
    "Document context:\n{context}"
)


class OpenAINotConfiguredError(RuntimeError):
    pass


class OpenAIRequestError(RuntimeError):
    pass


def _render_block_text(block: dict[str, Any]) -> str:
    block_type = str(block.get("type", ""))
    if block_type in {"paragraph", "heading", "quote", "footnote", "caption", "formula"}:
        return str(block.get("text", "")).strip()
    if block_type == "list":
        return "\n".join(
            f"- {str(item.get('text', '')).strip()}"
            for item in block.get("items", [])
            if str(item.get("text", "")).strip()
        )
    if block_type == "table":
        caption = str(block.get("caption", "")).strip()
        lines = [f"Table: {caption}" if caption else "Table:"]
        for row in block.get("rows", []):
            cells = [str(cell.get("text", "")).strip() for cell in row]
            if any(cells):
                lines.append(" | ".join(cells))
        return "\n".join(lines) if len(lines) > 1 else ""
    if block_type == "figure":
        caption = str(block.get("caption", "")).strip()
        return f"Figure: {caption}" if caption else ""
    if block_type in {"box_section", "callout"}:
        return "\n".join(
            _render_block_text(child) for child in block.get("blocks", [])
        ).strip()
    if block_type == "group":
        return "\n".join(
            str(item.get("text", "")).strip()
            for item in block.get("items", [])
            if str(item.get("text", "")).strip()
        )
    return ""


def _section_text(section: dict[str, Any]) -> str:
    heading = str(section.get("displayTitle", "")).strip()
    section_lines = [f"## {heading}"] if heading else []
    for block in section.get("blocks", []):
        text = _render_block_text(block)
        if text:
            section_lines.append(text)
    return "\n".join(section_lines).strip()


def build_chat_context(
    structured: dict[str, Any], json_ld: dict[str, Any], question: str = ""
) -> str:
    """Condense a document's structured.json + schema.jsonld exports into a
    bounded plain-text context for the chat assistant.

    Most reports fit whole, in their original reading order, under
    CHAT_CONTEXT_CHAR_BUDGET. For documents that don't (long reports easily
    exceed it), forwarding just the first N characters means any question
    about later content silently gets no context at all. Instead, sections
    are ranked by keyword overlap with the current question and the
    highest-scoring ones are included — still assembled back into their
    original reading order — until the budget is used. This keeps context
    bounded for documents of any length while actually surfacing the part
    of the document the question is about, rather than an arbitrary prefix.
    """
    metadata = structured.get("metadata") or {}
    publication = structured.get("publication") or {}

    lines: list[str] = []

    def add(label: str, value: Any) -> None:
        text = str(value or "").strip()
        if text:
            lines.append(f"{label}: {text}")

    add("Title", metadata.get("title") or publication.get("sourceName"))
    add("Publisher", metadata.get("publisher"))
    add("Published", metadata.get("published_date") or metadata.get("publishedDate"))
    add("Jurisdiction", metadata.get("jurisdiction"))

    report_node = next(
        (
            node
            for node in json_ld.get("@graph", [])
            if isinstance(node, dict) and node.get("@type") == "Report"
        ),
        None,
    )
    if report_node:
        add("Description", report_node.get("description"))
        add("Accessibility summary", report_node.get("accessibilitySummary"))

    for value in publication.get("summary") or []:
        add("Summary", value)

    lines.append("")
    lines.append("Sections:")
    budget = CHAT_CONTEXT_CHAR_BUDGET - sum(len(line) + 1 for line in lines)

    sections = [
        (index, text)
        for index, section in enumerate(publication.get("sections", []))
        if (text := _section_text(section))
    ]
    total_length = sum(len(text) for _, text in sections)

    section_truncated = False
    if total_length <= budget:
        selected = sections
        omitted = 0
    else:
        query_words = _keywords(question)
        # Every question word that appears in the section, plus a small
        # recency-independent bonus for earlier sections (introductions and
        # executive summaries are disproportionately likely to be relevant
        # regardless of the specific question asked).
        def score(entry: tuple[int, str]) -> tuple[int, float]:
            index, text = entry
            overlap = len(query_words & _keywords(text)) if query_words else 0
            position_bonus = 1.0 / (index + 1)
            return (overlap, position_bonus)

        ranked = sorted(sections, key=score, reverse=True)
        selected = []
        used = 0
        for entry in ranked:
            _, text = entry
            if used + len(text) > budget:
                continue
            selected.append(entry)
            used += len(text)
        if not selected and ranked and budget > 0:
            # Every individual section is larger than the whole budget (one
            # huge chapter with no smaller sections to fall back to) — take
            # the best-matching one anyway, truncated, rather than leaving
            # the assistant with no document content at all.
            index, text = ranked[0]
            selected = [(index, text[:budget])]
            section_truncated = True
        omitted = len(sections) - len(selected)
        selected.sort(key=lambda entry: entry[0])

    for _, text in selected:
        lines.append(text)

    if omitted or section_truncated:
        lines.append(
            f"\n[{omitted} other section(s) of this document were omitted "
            "from this answer's context because it's longer than the "
            "assistant can read at once. If the answer isn't here, try "
            "asking about a specific chapter or topic by name.]"
        )

    return "\n".join(lines).strip()


async def stream_chat_completion(
    settings: Settings,
    context: str,
    message: str,
    history: list[dict[str, str]],
) -> AsyncIterator[str]:
    if not settings.openai_api_key:
        raise OpenAINotConfiguredError("OPENAI_API_KEY is not configured")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(context=context)},
        *history,
        {"role": "user", "content": message},
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{OPENAI_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={"model": CHAT_MODEL, "messages": messages, "stream": True},
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise OpenAIRequestError(
                    f"OpenAI chat request failed ({response.status_code}): "
                    f"{body.decode('utf-8', 'replace')}"
                )
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                content = (choices[0].get("delta") or {}).get("content")
                if content:
                    yield content


async def synthesize_speech(settings: Settings, text: str) -> AsyncIterator[bytes]:
    if not settings.openai_api_key:
        raise OpenAINotConfiguredError("OPENAI_API_KEY is not configured")

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{OPENAI_API_BASE}/audio/speech",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": TTS_MODEL,
                "voice": TTS_VOICE,
                "input": text,
                "response_format": "mp3",
            },
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise OpenAIRequestError(
                    f"OpenAI TTS request failed ({response.status_code}): "
                    f"{body.decode('utf-8', 'replace')}"
                )
            async for chunk in response.aiter_bytes():
                yield chunk
