from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DOC_TYPES = ("act", "report", "paper")


@dataclass(frozen=True)
class DocumentInfo:
    """Manifest entry: what the converter output cannot tell us (type, version, dates)."""

    doc_id: str
    doc_type: str
    title: str = ""
    publisher: str = ""
    published: str | None = None
    law_as_at: str | None = None
    version: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    file: str = ""
    source_url: str | None = None

    def __post_init__(self) -> None:
        if self.doc_type not in DOC_TYPES:
            raise ValueError(f"{self.doc_id}: doc_type must be one of {DOC_TYPES}")

    @property
    def source_file(self) -> str:
        return Path(self.file).name if self.file else ""

    @property
    def effective_from_date(self) -> str | None:
        """When the text starts to count: an explicit date, else the date it is stated
        as at (an Act version), else publication (a report or paper cannot predate itself)."""
        return self.effective_from or self.law_as_at or self.published


def load_manifest(path: Path) -> dict[str, DocumentInfo]:
    """documents.json -> {doc_id: DocumentInfo}. A doc_id may repeat only with distinct versions,
    in which case the key is doc_id@version."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, DocumentInfo] = {}
    known = set(DocumentInfo.__dataclass_fields__)
    for entry in raw["documents"]:
        info = DocumentInfo(**{k: v for k, v in entry.items() if k in known})
        key = f"{info.doc_id}@{info.version}" if info.version else info.doc_id
        if key in out:
            raise ValueError(f"duplicate manifest entry {key}")
        out[key] = info
    return out


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_type: str
    section_id: str
    heading_path: list[str]
    text: str
    page_start: int | None
    page_end: int | None
    source_file: str
    version: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def embed_text(self) -> str:
        """What gets embedded (and hashed): the heading path travels with every piece."""
        return (" > ".join(self.heading_path) + "\n\n" if self.heading_path else "") + self.text

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.embed_text.encode("utf-8")).hexdigest()

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["content_hash"] = self.content_hash
        return row


@dataclass(frozen=True)
class Link:
    from_section: str      # e.g. "report:rec-22"
    to_section: str        # e.g. "act:s-77"
    kind: str              # refers_to | amends | responds_to
    doc_id: str            # document the reference was found in
    evidence: str = ""     # the matched text, for audit

    def to_row(self) -> dict[str, Any]:
        return asdict(self)
