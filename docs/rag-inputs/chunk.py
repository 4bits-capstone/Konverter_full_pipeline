#!/usr/bin/env python3
"""Split the benchmark documents into section-level chunks with stable section IDs.

Every setup (A: vector, B: vector + metadata filter, C: graph) loads the SAME chunks, and the gold
questions name the sections that answer them by these IDs, so retrieval can be scored without an LLM.

Section IDs, per document type:
  act     s-77                    a numbered section ("77 Entitlements of right of interment ...")
  report  rec-2, para-7.4         a numbered recommendation, or a numbered paragraph
  paper   q-9, para-3.12          a numbered consultation question, or a numbered paragraph
Text before the first recognised unit in a heading section gets the heading's slug (e.g. "h-introduction").

Input is the Konverter (Docling) markdown for each document: data/markdown/<doc_id>.md. Headings
(#..######) give the heading path; recommendations and questions are recognised inside headings called
"Recommendations" / "Questions".

  python3 pipeline/chunk.py                 writes data/chunks.jsonl from data/documents.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
MAX_CHARS = 2500        # longer units are split into parts that keep the same section_id

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
ACT_SECTION = re.compile(r"^\**\s*(\d{1,3}[A-Z]{0,2})\s+(?=[A-Z])")          # "77 Entitlements of ..."
PARAGRAPH = re.compile(r"^\**\s*(\d{1,2}\.\d{1,3})\s+(?=\S)")                 # "7.4 The cemetery trust ..."
NUMBERED = re.compile(r"^\**\s*(\d{1,2})[.)]?\s+(?=\S)")                       # "2 The person with ..." in a list


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "untitled"


def unit_id(line: str, doc_type: str, heading: str) -> str | None:
    """The section ID a line starts, or None if it continues the current unit."""
    h = heading.lower()
    if doc_type == "report" and h.startswith("recommendation") and (m := NUMBERED.match(line)):
        return f"rec-{m.group(1)}"
    if doc_type == "paper" and h.startswith("question") and (m := NUMBERED.match(line)):
        return f"q-{m.group(1)}"
    if doc_type in ("report", "paper") and (m := PARAGRAPH.match(line)):
        return f"para-{m.group(1)}"
    if doc_type == "act" and (m := ACT_SECTION.match(line)):
        return f"s-{m.group(1)}"
    return None


def units(markdown: str, doc_type: str) -> Iterator[tuple[str, list[str], str]]:
    """(section_id, heading_path, text) for each unit, in document order."""
    path: list[str] = []
    current, buf = None, []

    def flush() -> Iterator[tuple[str, list[str], str]]:
        text = "\n".join(buf).strip()
        if text:
            yield current or f"h-{slug(path[-1] if path else 'start')}", list(path), text

    for line in markdown.splitlines():
        if m := HEADING.match(line):
            yield from flush()
            level, title = len(m.group(1)), m.group(2).strip()
            path = path[: level - 1] + [title]
            current, buf = None, []
            # An act section often arrives as its own heading ("## 77 Entitlements of ...").
            if doc_type == "act" and (s := ACT_SECTION.match(title)):
                current = f"s-{s.group(1)}"
            continue
        sid = unit_id(line.strip(), doc_type, path[-1] if path else "")
        if sid and sid != current:
            yield from flush()
            current, buf = sid, []
        buf.append(line)
    yield from flush()


def split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(para) + 2 > limit:
            parts.append(cur)
            cur = ""
        while len(para) > limit:             # a single huge paragraph: hard-split it
            parts.append(para[:limit])
            para = para[limit:]
        cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def chunk_document(doc: dict[str, Any], markdown: str) -> list[dict[str, Any]]:
    out, seen = [], {}
    for sid, path, text in units(markdown, doc["doc_type"]):
        n = seen[sid] = seen.get(sid, 0) + 1      # the same ID twice (e.g. a heading repeated): keep both
        for i, part in enumerate(split_long(text)):
            chunk_id = f"{doc['doc_id']}:{sid}" + (f"~{n}" if n > 1 else "") + (f"#{i + 1}" if i else "")
            out.append({
                "chunk_id": chunk_id,
                "doc_id": doc["doc_id"],
                "section_id": f"{doc['doc_id']}:{sid}",
                "heading_path": path,
                "text": part,
                "metadata": {k: doc.get(k) for k in ("doc_type", "title", "published", "law_as_at", "version")},
            })
    return out


def main(argv: list[str]) -> int:
    manifest = json.loads((ROOT / "data/documents.json").read_text())
    rows, missing = [], []
    for doc in manifest["documents"]:
        md = ROOT / "data/markdown" / f"{doc['doc_id']}.md"
        if not md.exists():
            missing.append(str(md.relative_to(ROOT)))
            continue
        rows += chunk_document(doc, md.read_text())
    if missing:
        print("Missing Konverter markdown (convert the PDFs in data/raw first): " + ", ".join(missing), file=sys.stderr)
    out = ROOT / "data/chunks.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{len(rows)} chunks -> {out.relative_to(ROOT)}")
    # Every gold section must exist as a chunk, or the scores would silently undercount.
    import csv
    have = {r["section_id"] for r in rows}
    with (ROOT / "eval/questions.csv").open(newline="") as f:
        gold = {g for q in csv.DictReader(f) for g in q["gold_sections"].split(";") if g}
    lost = sorted(g for g in gold if g not in have and g.split(":")[0] in {r["doc_id"] for r in rows})
    if lost:
        print("Gold sections with no matching chunk (fix the question or the chunking): " + ", ".join(lost), file=sys.stderr)
    return 1 if missing or lost else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
