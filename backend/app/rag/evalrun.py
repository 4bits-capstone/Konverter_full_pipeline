"""eval: run every question in questions.csv through ask and write one JSON line per question.

Each line has what eval/score.py reads (question_id, setup, retrieved[], abstained, latency_ms) plus the answer.
`retrieved` is the ranked section list BEFORE the similarity floor (so setups compare on ranking alone); the sections the
answer actually saw are in `used`. `top_similarity` is the best vector score, for calibrating the floor on unanswerable questions.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .answer import ranked_sections
from .ask import ask
from .embeddings import Embedder
from .llm import LLM
from .retrieve import RetrievalOptions
from .settings import RagSettings
from .store import Store


def load_questions(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run_eval(questions: Iterable[dict[str, str]], embedder: Embedder, store: Store, llm: LLM, settings: RagSettings,
             options: RetrievalOptions, setup: str) -> Iterable[dict[str, Any]]:
    for q in questions:
        result, _ = ask(q["question"], embedder, store, llm, settings, options)
        ranked = result["ranked"]
        yield {
            "question_id": q["id"], "setup": setup, "category": q.get("category"),
            "retrieved": ranked_sections(result), "used": result["retrieved"],
            "answer": result["answer"], "citations": result["citations"], "abstained": result["abstained"],
            "abstain_reason": result.get("abstain_reason"), "latency_ms": result["latency_ms"], "model": result.get("model"),
            "top_similarity": next((r["similarity"] for r in ranked if r["similarity"] is not None), None),
            **({"error": result["error"]} if result.get("error") else {}),
        }


def write_results(rows: Iterable[dict[str, Any]], out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            count += 1
    return count
