"""Answering: build the prompt from retrieved chunks, call the LLM, validate, and enforce the rules.

The same prompt text (prompts/answer_system.txt) and the same output shape are used by the n8n Ask
workflow. Rules enforced here, not left to the model:
  * nothing retrieved (or everything below the similarity floor) -> "Not found", the LLM is not called;
  * citations are kept only if they name a retrieved section (or one listed in a chunk's `contains`);
  * an answer with no valid citation is turned into an abstention;
  * the LLM failing or returning junk is an abstention with the error, never an invented answer.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Sequence

from .llm import LLM, LLMError
from .settings import RagSettings

NOT_FOUND = "Not found in the provided documents."
PROMPT_PATH = Path(__file__).parent / "prompts" / "answer_system.txt"
_INLINE_ID = re.compile(r"\[([a-z]+:[A-Za-z0-9._-]+)\]")


def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def usable_rows(rows: Sequence[dict[str, Any]], min_similarity: float) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("chunk_id") and float(r.get("similarity") or 0) >= min_similarity]


def _header(row: dict[str, Any]) -> str:
    meta = row.get("metadata") or {}
    pages = row.get("page_start"), row.get("page_end")
    where = [
        meta.get("title") or row.get("doc_id"),
        f"version {row['version']}" if row.get("version") else None,
        " > ".join(row.get("heading_path") or []) or None,
        (f"p. {pages[0]}" if pages[0] == pages[1] else f"pp. {pages[0]}-{pages[1]}") if pages[0] else None,
        f"contains: {', '.join(meta['contains'])}" if meta.get("contains") else None,
    ]
    return f"[{row['section_id']}] ({' | '.join(w for w in where if w)})"


def build_messages(question: str, rows: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    passages = "\n\n---\n\n".join(f"{_header(r)}\n{r['content']}" for r in rows)
    return [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": f"PASSAGES:\n\n{passages}\n\nQUESTION: {question}"},
    ]


def ranked_sections(result: dict[str, Any]) -> list[str]:
    """Pre-floor ranked section IDs, de-duplicated: the `retrieved` list the eval scores."""
    return list(dict.fromkeys(item["section_id"] for item in result["ranked"]))


def allowed_citations(rows: Sequence[dict[str, Any]]) -> set[str]:
    allowed = {r["section_id"] for r in rows}
    for r in rows:
        allowed.update((r.get("metadata") or {}).get("contains") or [])
    return allowed


def _parse(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    return data


def answer_question(question: str, rows: Sequence[dict[str, Any]], llm: LLM, settings: RagSettings,
                    started: float | None = None) -> dict[str, Any]:
    """`rows` are match_chunks results (best first). Returns the JSON the n8n workflow also returns."""
    started = time.monotonic() if started is None else started
    kept = usable_rows(rows, settings.min_similarity)
    # Everything match_chunks returned, before the similarity floor. Retrieval quality (recall@k, MRR) is
    # measured on this, so setups compare on ranking alone; `retrieved` / `scores` are what the answer saw.
    ranked = [{"chunk_id": r["chunk_id"], "section_id": r["section_id"], "similarity": round(float(r.get("similarity") or 0), 3)}
              for r in rows if r.get("chunk_id")]
    retrieved = list(dict.fromkeys(r["section_id"] for r in kept))
    scores = [{"chunk_id": r["chunk_id"], "section_id": r["section_id"], "similarity": round(float(r["similarity"]), 3)} for r in kept]

    def result(**fields: Any) -> dict[str, Any]:
        base = {"answer": NOT_FOUND, "citations": [], "unsupported_citations": [], "abstained": True,
                "retrieved": retrieved, "scores": scores, "ranked": ranked, "latency_ms": round((time.monotonic() - started) * 1000)}
        return {**base, **fields}

    if not kept:
        return result(abstain_reason="no_passages")
    try:
        reply = llm.complete(build_messages(question, kept))
        data = _parse(reply.content)
    except (LLMError, ValueError) as exc:     # JSONDecodeError is a ValueError
        return result(answer="Sorry, the answer could not be generated.", abstain_reason="llm_error", error=str(exc)[:300])

    allowed = allowed_citations(kept)
    claimed = list(dict.fromkeys(str(c) for c in (data.get("citations") if isinstance(data.get("citations"), list) else [])))
    in_text = [i for i in _INLINE_ID.findall(str(data.get("answer") or "")) if i not in claimed]
    valid = [c for c in claimed if c in allowed]
    unsupported = [c for c in [*claimed, *in_text] if c not in allowed]
    meta = {"model": reply.model or llm.model, "usage": reply.usage}
    if data.get("abstained") is True:
        return result(abstain_reason="model", unsupported_citations=unsupported, **meta)
    if not valid:
        # An answer nobody can trace to a retrieved section is not an answer.
        return result(abstain_reason="no_valid_citations", unsupported_citations=unsupported, **meta)
    return result(answer=str(data.get("answer") or "").strip(), citations=valid, unsupported_citations=unsupported,
                  abstained=False, **meta)
