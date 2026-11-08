"""Render backend/sql/006_rag_chunks.sql for a given embedding size."""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "sql" / "006_rag_chunks.sql"
PLACEHOLDER = "{{EMBEDDING_DIM}}"


def render_sql(dimension: int, template: Path = TEMPLATE) -> str:
    if not 1 <= int(dimension) <= 2000:
        raise ValueError("embedding dimension must be between 1 and 2000")
    if not template.is_file():
        raise FileNotFoundError(f"SQL template not found: {template} (the SQL is not shipped in the container image)")
    text = template.read_text(encoding="utf-8")
    rendered = text.replace(PLACEHOLDER, str(int(dimension)))
    if re.search(r"\{\{[A-Z_]+\}\}", rendered):
        raise ValueError("unrendered placeholder left in SQL")
    return rendered
