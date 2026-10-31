"""ask: retrieve (optionally following links) and answer. The Python twin of the n8n Ask workflow."""
from __future__ import annotations

import time
from typing import Any

from .answer import answer_question
from .embeddings import Embedder
from .llm import LLM
from .retrieve import RetrievalOptions, retrieve
from .settings import RagSettings
from .store import Store


def ask(question: str, embedder: Embedder, store: Store, llm: LLM, settings: RagSettings,
        options: RetrievalOptions | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(result, rows). `result` is the n8n response JSON; `rows` are everything retrieval returned, best first."""
    started = time.monotonic()
    options = options or RetrievalOptions(k=settings.top_k)
    rows = retrieve(question, embedder, store, options)
    return answer_question(question, rows, llm, settings, started), rows
