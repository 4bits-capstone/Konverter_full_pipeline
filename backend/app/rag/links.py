"""Cross-reference extraction: "see section 12", "Recommendation 7", "Question 9".

Fail closed: a reference becomes a link only when its target resolves to a section
that exists in the known set. Anything ambiguous (a "section 5" of some other
statute, an unknown recommendation) is dropped rather than guessed.
"""
from __future__ import annotations

import re
from typing import Iterable

from .chunking import _INLINE_NOTE
from .models import Chunk, Link

_NUM = r"\d{1,3}[A-Z]{0,2}"
_LIST_TAIL = rf"(?:\s*(?:,|and|or|to|–|-)\s*{_NUM}\b(?!\s*(?:years|per|%)))*"
_SECTION = re.compile(rf"\b(?:sections?|ss?)\s+({_NUM}){_LIST_TAIL}", re.IGNORECASE)
_REC = re.compile(rf"\bRecommendations?\s+(\d{{1,2}}){_LIST_TAIL}")
_QUESTION = re.compile(rf"\b(?:Questions?|Q)\s+(\d{{1,2}}){_LIST_TAIL}")
_NUMBER = re.compile(_NUM)
_AMENDS = re.compile(r"\bamend(?:s|ed|ing|ment)?\b", re.IGNORECASE)
# Statutes we can resolve a bare "section N" in a report to.
_ACT_NAMES = ("Cemeteries and Crematoria Act",)
# What follows "section 12": "of the Wills Act 1997 (Vic)", "of this Act", "of the Act".
_OWNER = re.compile(
    r"^(?:\([^)]*\))*(?:\s*,?\s*(?:and|or)\s+\d{1,3}[A-Z]{0,2}(?:\([^)]*\))*)*\s+of\s+(?:the\s+)?(this Act|Act\b|[A-Z][A-Za-z ,'’-]{0,80}?\bAct\b(?:\s+\d{4})?)"
)


def _owner(text: str, match: re.Match[str]) -> str | None:
    found = _OWNER.match(text[match.end() :])
    return found.group(1).strip() if found else None


# "No. 61/2009 s. 9", "Nos 61/2009 s. 40, 16/2021 s. 11(3)", "No. 4/2015 ss 4 - 8": citations of the AMENDING Act.
# Margin history notes are made of these; the sections they name belong to another Act, so they are never links.
_AMENDING_CITATION = re.compile(
    r"\bNos?\.?\s*\d+/\d{4}(?:\s*(?:,|and)?\s*(?:ss?\.?\s?\d+[A-Z]{0,2}(?:\([^)]*\))*(?:\s*[–-]\s*\d+[A-Z]{0,2})?|\d+/\d{4}))*",
    re.IGNORECASE,
)


def strip_history_notes(text: str) -> str:
    """Remove legislative history notes, whole or fragmentary, so their section numbers are never read."""
    return _AMENDING_CITATION.sub(" ", _INLINE_NOTE.sub(" ", text))


def _numbers(match: re.Match[str]) -> list[str]:
    return _NUMBER.findall(match.group(0).split(None, 1)[1])


def _window(text: str, match: re.Match[str], width: int = 80) -> str:
    return text[max(0, match.start() - width) : match.end() + width]


def extract_links(chunks: Iterable[Chunk], known_sections: set[str]) -> list[Link]:
    """Links found in `chunks`, resolved against `known_sections` ("report:rec-2", "act:s-77", ...)."""
    found: dict[tuple[str, str, str], Link] = {}

    def add(chunk: Chunk, target: str, kind: str, evidence: str) -> None:
        if target not in known_sections or target == chunk.section_id:
            return
        found.setdefault(
            (chunk.section_id, target, kind),
            Link(chunk.section_id, target, kind, chunk.doc_id, evidence.strip()[:160]),
        )

    for chunk in chunks:
        text = strip_history_notes(chunk.text)
        if chunk.doc_type == "act":
            for m in _SECTION.finditer(text):
                owner = _owner(text, m)
                if owner and owner not in ("this Act", "Act") and not any(a in owner for a in _ACT_NAMES):
                    continue  # a section of some other statute
                for n in _numbers(m):
                    add(chunk, f"{chunk.doc_id}:s-{n}", "refers_to", m.group(0))
            continue
        for m in _REC.finditer(text):
            for n in _numbers(m):
                add(chunk, f"{chunk.doc_id}:rec-{n}", "refers_to", m.group(0))
        for m in _QUESTION.finditer(text):
            if chunk.doc_type == "report":
                # Only an explicit pointer at the consultation paper; a report's survey
                # appendix also numbers its own "Question 1..".
                if "consultation paper" not in _window(text, m, 160).lower():
                    continue
                kind, target_doc = "responds_to", "paper"
            else:
                kind, target_doc = "refers_to", chunk.doc_id
            for n in _numbers(m):
                add(chunk, f"{target_doc}:q-{n}", kind, m.group(0))
        for m in _SECTION.finditer(text):
            context = _window(text, m)
            owner = _owner(text, m)
            if owner is None or not (
                any(a in owner for a in _ACT_NAMES) or (owner in ("this Act", "Act") and any(a in text for a in _ACT_NAMES))
            ):
                continue  # which statute? unknown or another one -> drop
            kind = "amends" if _AMENDS.search(context) else "refers_to"
            for n in _numbers(m):
                add(chunk, f"act:s-{n}", kind, context)
    return list(found.values())
