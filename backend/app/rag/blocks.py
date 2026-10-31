"""Flatten a Konverter structured.json into an ordered stream of typed lines.

The converter keeps structure but not "units": a recommendation is a list item whose
number is only part of its text, its (a)/(b) sub-items arrive as a separate sibling
list, and an Act section is a heading or paragraph that starts with its number. The
chunker works on this stream so that page numbers survive (markdown would lose them).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class Line:
    kind: str                 # heading | para | item | table | caption
    text: str
    page: int | None = None
    level: int = 0            # heading level (1 = chapter), or list nesting for items
    number: str | None = None # converter's own paragraph number, e.g. "7.4"
    marker: str = ""          # list marker, e.g. "(a)"
    rows: list[list[str]] | None = None  # table cells, kept so layouts Docling mis-typed can be recovered


def _page(block: dict[str, Any], default: int | None) -> int | None:
    page = block.get("page")
    return int(page) if isinstance(page, (int, float)) else default


def _cell(cell: Any) -> str:
    # Rows hold plain strings, or Docling cell dicts ({"text": ..., "rowSpan": ...}).
    return str(cell.get("text", "") if isinstance(cell, dict) else cell).strip()


def _table_text(block: dict[str, Any]) -> str:
    rows = [" | ".join(_cell(cell) for cell in row) for row in block.get("rows") or []]
    caption = str(block.get("caption") or "").strip()
    return "\n".join(([caption] if caption else []) + rows)


def _blocks(blocks: list[dict[str, Any]], page: int | None) -> Iterator[Line]:
    for block in blocks:
        kind = block.get("type")
        bpage = _page(block, page)
        if kind == "heading":
            yield Line("heading", str(block.get("text") or "").strip(), bpage, level=int(block.get("level") or 2))
        elif kind in ("paragraph", "quote"):
            text = str(block.get("text") or "").strip()
            if text:
                yield Line("para", text, bpage, number=block.get("number") or None)
        elif kind == "list":
            for item in block.get("items") or []:
                text = str(item.get("text") or "").strip()
                if text:
                    yield Line("item", text, bpage, level=int(item.get("level") or 0), marker=str(item.get("marker") or ""))
        elif kind == "table":
            text = _table_text(block)
            if text:
                rows = [[_cell(c) for c in row] for row in block.get("rows") or []]
                yield Line("table", text, bpage, rows=rows)
        elif kind in ("figure", "caption"):
            text = str(block.get("caption") or block.get("text") or "").strip()
            if text:
                yield Line("caption", text, bpage)
        elif kind == "group":
            for item in block.get("items") or []:
                text = str(item.get("text") or "").strip()
                if text:
                    yield Line("para", text, bpage)
        elif kind == "box_section":
            title = str(block.get("title") or "").strip()
            if title:
                yield Line("para", title, bpage)
            yield from _blocks(block.get("blocks") or [], bpage)


def flatten(structured: dict[str, Any]) -> Iterator[Line]:
    """Every section becomes a level-1 heading followed by its blocks, in reading order."""
    publication = structured.get("publication") or structured
    for section in publication.get("sections") or []:
        title = str(section.get("displayTitle") or section.get("title") or "").strip()
        page = _page(section, None)
        if title and section.get("id") != "front-matter":
            yield Line("heading", title, page, level=1)
        yield from _blocks(section.get("blocks") or [], page)
