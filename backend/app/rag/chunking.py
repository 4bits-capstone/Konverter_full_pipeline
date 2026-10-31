"""Structure-aware chunking on legal units.

A unit is an Act section, a recommendation, a numbered report/paper paragraph or a
consultation question. Units are never merged and never split mid-sentence unless a
single sentence exceeds the limit; long units are cut at subsection boundaries and
every piece repeats the heading path. Section IDs follow the benchmark's conventions
(act:s-77, report:rec-2, report:para-7.4, paper:q-9) so gold questions can name them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from .blocks import Line, flatten
from .models import Chunk, DocumentInfo

MAX_CHARS = 2500

_REC_HEAD = re.compile(r"^(\d{1,2})\s+(?=\S)")
_PARA_NUM = re.compile(r"^\d{1,2}\.\d{1,3}$")
_BARE_NUM = re.compile(r"^\d{1,2}$")
_ACT_SECTION = re.compile(r"^(\d{1,3})([A-Z]{0,2})\s+(?=[A-Z])")
_SUBSECTION = re.compile(r"^\(\d{1,3}[A-Z]{0,2}\)\s")
_CLAUSE = re.compile(r"^\((?:\d{1,3}[A-Z]{0,2}|[a-z]{1,4}|[A-Z]{1,2})\)\s")
_STRUCTURE = re.compile(r"^(Part|Division|Subdivision|Schedule)\s+(\d+[A-Z]{0,2})\s*[—–-]", re.IGNORECASE)
_RUNNING_HEADER = re.compile(r"\bAct \d{4} No\. \d+ of \d{4}\s*$")
_HISTORY_NOTE = re.compile(r"^Ss?\.?\s*\d+[A-Z]{0,2}\b")
_INLINE_NOTE = re.compile(
    r"\bSs?\. ?\d+[A-Z]{0,2}(?:\([^)]*\))*(?: (?:def\.|pt\.|heading|[a-z]+) [^()]{0,60}?)? ?"
    r"(?:inserted|substituted|amended|repealed|omitted|renumbered)\s?by\s+(?:No\.|Act)\s?\d+/\d{4}(?: ss?\. ?\d+[A-Z]{0,2}(?:\([^)]*\))*)?",
    re.IGNORECASE,
)
_TERMINAL = (".", ";", ":", "—", "?", "!", ")")
_MAX_SECTION_JUMP = 8


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "untitled"


@dataclass
class Unit:
    sid: str
    path: list[str]
    atoms: list[Line] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # legislative history margin notes ("S. 5A inserted by ...")


@dataclass
class ChunkReport:
    chunks: list[Chunk]
    duplicates_dropped: int = 0
    warnings: list[str] = field(default_factory=list)
    unit_counts: dict[str, int] = field(default_factory=dict)


def _atom_text(line: Line) -> str:
    if line.kind == "item":
        return "  " * line.level + (f"{line.marker} " if line.marker else "") + line.text
    return line.text


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# --- unit segmentation -------------------------------------------------------------------

def _expand_rec_tables(lines: list[Line]) -> list[Line]:
    """Docling sometimes lays a run of recommendations out as a 3-column table
    (number | text | blank, with (a)/(b) sub-rows). Turn those rows back into the same
    item lines a normally parsed recommendation list produces."""
    out: list[Line] = []
    in_recs = False
    for line in lines:
        if line.kind == "heading":
            in_recs = line.text.lower().startswith("recommendation") or (
                in_recs and line.level > 1
            )
        if not (in_recs and line.kind == "table" and line.rows):
            out.append(line)
            continue
        numbered = [r for r in line.rows if r and _BARE_NUM.match(r[0])]
        if not numbered:
            out.append(line)
            continue
        for row in line.rows:
            first = row[0] if row else ""
            if _BARE_NUM.match(first) and len(row) > 1 and row[1]:
                out.append(Line("item", f"{first} {row[1]}", line.page))
            elif not first and len(row) > 2 and row[1] and row[2]:
                out.append(Line("item", row[2], line.page, marker=row[1]))
    return out


def _units_prose(lines: list[Line], doc_type: str) -> Iterator[Unit]:
    """Reports and consultation papers: heading levels give the path."""
    path: list[str] = []
    current: Unit | None = None
    last_rec = 0
    rec_heads: dict[int, str] = {}   # canonical recommendation openings, to recognise their repeats
    expect_question = False

    def start(sid: str) -> Unit:
        return Unit(sid, list(path))

    for line in lines:
        if line.kind == "heading":
            if current:
                yield current
            path = path[: max(line.level - 1, 0)] + [line.text]
            current, expect_question = None, False
            continue
        if line.kind == "para" and line.text.strip().lower() in ("recommendation", "recommendations") and path and not path[-1].lower().startswith("recommendation"):
            continue  # call-out label, not content
        in_recs = any(p.lower().startswith("recommendation") for p in path)
        in_questions = path and path[-1].lower().startswith("question")
        sid: str | None = None
        if doc_type == "report" and in_recs and line.kind == "item" and not line.marker:
            m = _REC_HEAD.match(line.text)
            if m and int(m.group(1)) == last_rec + 1:
                last_rec = int(m.group(1))
                sid = f"rec-{last_rec}"
                rec_heads[last_rec] = _norm(line.text[m.end() :])
        elif doc_type == "report" and line.kind == "item" and not line.marker and rec_heads:
            # A chapter repeats each recommendation in a call-out; it belongs to the
            # recommendation, not to the numbered paragraph above it.
            m = _REC_HEAD.match(line.text)
            if m and rec_heads.get(int(m.group(1))) == _norm(line.text[m.end() :]):
                sid = f"rec-{m.group(1)}"
        elif doc_type == "paper":
            if line.kind == "para" and line.text.strip().lower() == "question":
                expect_question = True
                continue  # the callout label itself is not content
            if expect_question and line.kind == "item" and (m := _REC_HEAD.match(line.text)):
                sid, expect_question = f"q-{m.group(1)}", False
            elif in_questions and line.kind == "para" and line.number and _BARE_NUM.match(line.number):
                sid = f"q-{line.number}"
        if sid is None and line.kind == "para" and line.number and _PARA_NUM.match(line.number):
            sid = f"para-{line.number}"
        if sid:
            if current:
                yield current
            current = start(sid)
        elif current is not None and current.sid.startswith(("q-", "rec-")) and not (line.kind == "item" and line.marker):
            # A question is its head plus (a)/(b) sub-items. Anything after (a footnote,
            # the next callout's prose, end matter) is not part of it.
            yield current
            current = start(f"h-{slug(path[-1] if path else 'start')}")
        elif current is None:
            current = start(f"h-{slug(path[-1] if path else 'start')}")
        current.atoms.append(line)
    if current:
        yield current


def _units_act(lines: list[Line], title: str) -> Iterator[Unit]:
    """Acts: Part/Division/Schedule headings give the path; "77 Title" headings start sections."""
    root = title.split(" (Vic)")[0].split(",")[0].strip() or "Act"
    stack: list[tuple[int, str]] = []          # (rank, text) for Part > Division > Subdivision
    schedule = ""
    current: Unit | None = None
    last_n, last_suffix = 0, ""
    skipping = False                            # inside the Table of Provisions

    def path() -> list[str]:
        return [root] + [text for _, text in stack]

    ranks = {"part": 1, "schedule": 1, "division": 2, "subdivision": 3}
    for line in lines:
        text = line.text.strip()
        if line.kind == "para" and text.lower().startswith("endnotes"):
            break                               # amendment history after the Act proper
        if line.kind == "heading":
            if re.match(r"^(table of provisions|contents)\b", text, re.IGNORECASE):
                skipping = True
                continue
            m = _STRUCTURE.match(text)
            if m:
                skipping = False
                if current:
                    yield current
                    current = None
                rank = ranks[m.group(1).lower()]
                stack = [(r, t) for r, t in stack if r < rank] + [(rank, text)]
                if m.group(1).lower() == "schedule":
                    schedule, last_n, last_suffix = m.group(2), 0, ""
                continue
            if skipping:
                continue
            s = _ACT_SECTION.match(text)
            if s:
                n, suffix = int(s.group(1)), s.group(2)
                # Numbers must keep climbing (a reset means a Schedule, a table row or
                # noise); the first section seen may start anywhere.
                ok = last_n == 0 or (last_n <= n <= last_n + _MAX_SECTION_JUMP and (n > last_n or suffix > last_suffix))
                if ok:
                    if current:
                        yield current
                    last_n, last_suffix = n, suffix
                    sid = f"sch{schedule}-{n}{suffix}" if schedule else f"s-{n}{suffix}"
                    current = Unit(sid, path(), [Line("heading", text, line.page)])
                    continue
            # Docling sometimes tags "Note"/"Example"/definitions as headings: keep as text.
            line = Line("para", text, line.page)
        elif line.kind == "para" and len(text) <= 120 and not text.endswith(_TERMINAL) and (s := _ACT_SECTION.match(text)):
            # ...and sometimes types a real section heading as a paragraph.
            n, suffix = int(s.group(1)), s.group(2)
            if not schedule and last_n < n <= last_n + _MAX_SECTION_JUMP and last_n:
                if current:
                    yield current
                last_n, last_suffix = n, suffix
                current = Unit(f"s-{n}{suffix}", path(), [Line("heading", text, line.page)])
                continue
        if skipping or current is None:
            continue                            # cover, table of provisions, Act preamble
        if line.kind == "para" and (_RUNNING_HEADER.search(text) or _STRUCTURE.match(text)):
            continue                            # page furniture repeating the current Part heading
        if line.kind == "para" and _HISTORY_NOTE.match(text):
            current.notes.append(text)          # margin note, not enacted text
            continue
        if _INLINE_NOTE.search(text):           # Docling folds some margin notes into the clause text
            current.notes += [m.group(0) for m in _INLINE_NOTE.finditer(text)]
            text = re.sub(r"\s{2,}", " ", _INLINE_NOTE.sub("", text)).strip()
            if not text:
                continue
            line = Line(line.kind, text, line.page, line.level, line.number, line.marker)
        current.atoms.append(line)
    if current:
        yield current


# --- splitting ---------------------------------------------------------------------------

def _sentences(text: str, limit: int) -> list[str]:
    parts, cur = [], ""
    for sentence in re.split(r"(?<=[.;:?!])\s+", text):
        while len(sentence) > limit:            # no punctuation at all: hard cut as a last resort
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        if cur and len(cur) + len(sentence) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur = f"{cur} {sentence}".strip()
    if cur:
        parts.append(cur)
    return parts


def _join_fragments(atoms: list[Line]) -> list[tuple[str, Line]]:
    """(text, first line) per atom; Docling's mid-sentence line breaks are rejoined."""
    out: list[tuple[str, Line]] = []
    for line in atoms:
        text = _atom_text(line)
        if (
            out
            and line.kind == "para"
            and not _CLAUSE.match(line.text)
            and out[-1][1].kind == "para"
            and not out[-1][0].rstrip().endswith(_TERMINAL)
        ):
            out[-1] = (f"{out[-1][0]} {text}", out[-1][1])
            continue
        out.append((text, line))
    return out


def _pieces(atoms: list[Line], limit: int) -> list[tuple[str, list[Line]]]:
    """Cut a unit into (text, lines) pieces <= limit, only at atom or subsection boundaries."""
    rendered = _join_fragments(atoms)
    groups: list[list[tuple[str, Line]]] = []
    for item in rendered:
        if not groups or _SUBSECTION.match(item[1].text):
            groups.append([])
        groups[-1].append(item)

    pieces: list[tuple[str, list[Line]]] = []
    cur_text, cur_lines = "", []

    def flush() -> None:
        nonlocal cur_text, cur_lines
        if cur_text:
            pieces.append((cur_text, cur_lines))
        cur_text, cur_lines = "", []

    def add(text: str, lines: list[Line]) -> None:
        nonlocal cur_text, cur_lines
        if cur_text and len(cur_text) + len(text) + 1 > limit:
            flush()
        cur_text = f"{cur_text}\n{text}" if cur_text else text
        cur_lines = cur_lines + lines

    for group in groups:
        size = sum(len(t) + 1 for t, _ in group)
        if size <= limit:
            add("\n".join(t for t, _ in group), [l for _, l in group])
            continue
        for text, line in group:                # a long subsection: cut between its lines
            if len(text) <= limit:
                add(text, [line])
            else:
                for sentence in _sentences(text, limit):
                    flush()
                    add(sentence, [line])
                    flush()
    flush()
    return pieces


# --- public API --------------------------------------------------------------------------

def chunk_document(info: DocumentInfo, structured: dict[str, Any], max_chars: int = MAX_CHARS) -> ChunkReport:
    lines = [l for l in flatten(structured) if l.text.strip()]
    if info.doc_type == "act":
        units = _units_act(lines, info.title)
    else:
        units = _units_prose(_expand_rec_tables(lines) if info.doc_type == "report" else lines, info.doc_type)

    id_prefix = f"{info.doc_id}@{info.version}" if info.version else info.doc_id
    seen: dict[str, list[str]] = {}
    report = ChunkReport(chunks=[])
    metadata = {
        k: v
        for k, v in {
            "title": info.title,
            "publisher": info.publisher,
            "published": info.published,
            "law_as_at": info.law_as_at,
            "source_url": info.source_url,
        }.items()
        if v
    }
    for unit in units:
        body = re.sub(r"[^a-z0-9]+", " ", "\n".join(_norm(_atom_text(a)) for a in unit.atoms)).strip()
        if unit.sid.startswith(("q-", "rec-")):
            body = re.sub(r"^\d+\s+", "", body)   # "9 If people..." and the appendix's "If people..." are the same
        if not body.strip():
            continue
        previous = seen.setdefault(unit.sid, [])
        if body in previous:                    # e.g. the questions repeated in an appendix
            report.duplicates_dropped += 1
            continue
        previous.append(body)
        n = len(previous)
        report.unit_counts[unit.sid.split("-")[0] + "-"] = report.unit_counts.get(unit.sid.split("-")[0] + "-", 0) + 1
        for i, (text, lines_) in enumerate(_pieces(unit.atoms, max_chars)):
            pages = [l.page for l in lines_ if l.page is not None]
            report.chunks.append(
                Chunk(
                    chunk_id=f"{id_prefix}:{unit.sid}" + (f"~{n}" if n > 1 else "") + (f"#{i + 1}" if i else ""),
                    doc_id=info.doc_id,
                    doc_type=info.doc_type,
                    section_id=f"{info.doc_id}:{unit.sid}",
                    heading_path=unit.path,
                    text=text,
                    page_start=min(pages) if pages else None,
                    page_end=max(pages) if pages else None,
                    source_file=info.source_file,
                    version=info.version,
                    effective_from=info.effective_from_date,
                    effective_to=info.effective_to,
                    metadata={**metadata, **({"history_notes": unit.notes} if unit.notes else {})},
                )
            )
    if info.doc_type == "act":
        report.warnings += _act_gaps(report.chunks)
    return report


def _act_gaps(chunks: list[Chunk]) -> list[str]:
    """Docling occasionally loses a section heading; its text then sits inside the
    preceding section's chunks. Say so rather than guess the boundary."""
    numbers = sorted({int(m.group(1)) for c in chunks if (m := re.match(r"^\w+:s-(\d+)", c.section_id))})
    missing = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers)) if numbers else []
    if not missing:
        return []
    return [
        f"{chunks[0].doc_id}: no heading found for section(s) {', '.join(map(str, missing))} between s-{numbers[0]} "
        f"and s-{numbers[-1]} (lost by the converter, or repealed); their text, if present, is inside the previous section"
    ]
