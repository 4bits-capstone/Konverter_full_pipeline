"""Retrieval: embed the question, filter + vector search, optionally follow links one hop.

Links are OFF by default. When on, sections linked to the top results (either direction) are appended after the
vector results, at most `link_cap` of them, under the same document / date / metadata filters. They carry
`via_link` and no similarity, so the answer step keeps them regardless of the similarity floor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .embeddings import Embedder
from .store import Store

LINK_CAP = 3


@dataclass
class RetrievalOptions:
    k: int = 8
    doc_ids: Sequence[str] | None = None
    as_of_date: str | None = None
    meta_filter: dict[str, Any] = field(default_factory=dict)
    links: bool = False
    link_cap: int = LINK_CAP


def retrieve(question: str, embedder: Embedder, store: Store, options: RetrievalOptions) -> list[dict[str, Any]]:
    vector = embedder.embed([question], "query")[0]
    rows = store.match_chunks(vector, options.k, options.doc_ids, options.as_of_date, options.meta_filter or {})
    if not options.links or not rows:
        return rows
    seeds = list(dict.fromkeys(r["section_id"] for r in rows))
    linked = store.expand_links(seeds, seeds, options.doc_ids, options.as_of_date, options.meta_filter or {}, options.link_cap)
    return rows + [
        {**{k: v for k, v in r.items() if k not in ("via_section", "link_kind")}, "similarity": None,
         "via_link": {"from": r["via_section"], "kind": r["link_kind"]}}
        for r in linked
    ]
