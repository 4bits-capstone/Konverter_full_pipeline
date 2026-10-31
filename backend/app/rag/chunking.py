"""Structure-aware chunking on legal units.

A unit is an Act section, a recommendation, a numbered report/paper paragraph or a
consultation question. Units are never merged and never split mid-sentence unless a
single sentence exceeds the limit; long units are cut at subsection boundaries and
every piece repeats the heading path. Section IDs follow the benchmark's conventions
(act:s-77, report:rec-2, report:para-7.4, paper:q-9) so gold questions can name them.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

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
# Margin notes ("S. 6A inserted by No. 61/2009 s. 9.") are laid out beside the text, so the text layer
# interleaves them with the body, split over several lines. \s therefore also matches line breaks.
_INLINE_NOTE = re.compile(
    r"\b(?:Ss?|Sch)\.\s?\d+[A-Z]{0,2}(?:\s*(?:cl\.|item)\s*\d+[A-Z]{0,2})?(?:\s?\([^)]*\))*"
    r"(?:\s*(?:def\.|pt\.|heading|[a-z]+)\s*[^()]{0,60}?)?\s*"
    r"(?:inserted|substituted|amended|repealed|omitted|renumbered)\s*by\s+(?:Nos?\.?|Act)\s*\d+/\d{4}"
    r"(?:\s*(?:,|and)?\s*(?:ss?\.\s?\d+[A-Z]{0,2}(?:\([^)]*\))*|\d+/\d{4}))*\.?",
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
    contains: list[str] = field(default_factory=list)  # other sections whose text could not be separated out
    text_source: str | None = None                      # "pdf-text-layer" when rebuilt from the PDF itself


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
    discard_tail = False     # after the appendix list of questions: end matter, not content

    def start(sid: str) -> Unit:
        return Unit(sid, list(path))

    for line in lines:
        if line.kind == "heading":
            if current:
                yield current
            path = path[: max(line.level - 1, 0)] + [line.text]
            current, expect_question, discard_tail = None, False, False
            continue
        if discard_tail and not (line.number and _BARE_NUM.match(line.number)):
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
            if in_questions:
                current, discard_tail = None, True
                continue
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

def chunk_document(
    info: DocumentInfo,
    structured: dict[str, Any],
    max_chars: int = MAX_CHARS,
    pdf_pages: Sequence[str] | None = None,
) -> ChunkReport:
    """`pdf_pages` is the PDF's own text layer, one string per page (see pdftext.py). When given,
    Act sections whose heading the converter lost are recovered from it."""
    lines = [l for l in flatten(structured) if l.text.strip()]
    gap_warnings: list[str] = []
    if info.doc_type == "act":
        units = _recover_missing_sections(list(_units_act(lines, info.title)), pdf_pages, info.doc_id, gap_warnings)
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
                    metadata={
                        **metadata,
                        **({"history_notes": unit.notes} if unit.notes else {}),
                        **({"contains": [f"{info.doc_id}:{unit.sid}", *unit.contains]} if unit.contains else {}),
                        **({"text_source": unit.text_source} if unit.text_source else {}),
                    },
                )
            )
    report.warnings += gap_warnings
    return report


# --- recovering sections the converter lost ------------------------------------------------
#
# Docling sometimes drops a section heading, splits "29" from its title, or loses the body
# altogether, so the text of section 5 ends up inside section 4 (a wrong citation) or nowhere.
# Gaps are found from the numbering. Each missing section is first cut out of the converter's own
# atoms; if that is not possible the whole affected span is rebuilt from the PDF text layer and
# marked metadata.text_source = "pdf-text-layer". If even that fails the chunk says what it
# contains (metadata.contains) so nothing is cited as the wrong section.

_SECTION_SID = re.compile(r"^s-(\d+)([A-Z]{0,2})$")
_PDF_FURNITURE = re.compile(
    r"^(?:Authorised by the Chief Parliamentary Counsel|No\. \d+ of \d{4}|.*\bAct \d{4}|\d{1,3}|[ivxlc]+|"
    r"(?:Part|Division|Subdivision)\s+\d+[A-Z]{0,2}\s*[—–-].*)\s*$",
    re.IGNORECASE,
)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _label(sid: str) -> str:
    return sid[2:]


def _missing_between(a: str, b: str) -> list[int]:
    ma, mb = _SECTION_SID.match(a), _SECTION_SID.match(b)
    if not (ma and mb):
        return []
    na, nb = int(ma.group(1)), int(mb.group(1))
    missing = list(range(na + 1, nb))
    if mb.group(2) and na < nb:          # "5A" without a "5" before it
        missing.append(nb)
    return missing


def _heading_re(label: str) -> re.Pattern[str]:
    return re.compile(rf"(?m)^{re.escape(label)}[ \t]+(?=[A-Z])")


def _heading_pages(label: str, pdf_pages: Sequence[str], lo: int, hi: int) -> bool:
    pattern = _heading_re(label)
    return any(pattern.search(pdf_pages[p - 1]) for p in range(max(lo, 1), min(hi, len(pdf_pages)) + 1))


def _split_at_heading(unit: Unit, n: int, pdf_pages: Sequence[str], lo: int, hi: int) -> Unit | None:
    """Cut `unit` where section `n` starts: find its heading and first body line in the PDF text
    layer, then the matching atom in the converter output."""
    pattern = _heading_re(str(n))
    for number in range(max(lo, 1), min(hi, len(pdf_pages)) + 1):
        for m in pattern.finditer(pdf_pages[number - 1]):
            window = _collapse(pdf_pages[number - 1][m.end() : m.end() + 900])
            for i, atom in enumerate(unit.atoms[1:], start=1):
                key = _collapse(_atom_text(atom))[:40]
                pos = window.find(key) if len(key) >= 8 else -1
                title = window[:pos].strip() if pos >= 0 else ""
                if 0 < pos <= 220 and title:
                    new = Unit(f"s-{n}", list(unit.path), [Line("heading", f"{n} {title}", number)] + unit.atoms[i:])
                    unit.atoms = unit.atoms[:i]
                    own = [x for x in unit.notes if re.match(rf"^Ss?\.?\s*{n}\b", x)]
                    new.notes = own
                    unit.notes = [x for x in unit.notes if x not in own]
                    return new
    return None


def _pdf_lines(pdf_pages: Sequence[str], lo: int, hi: int) -> list[tuple[int, str, bool]]:
    """(page, line, ends_with_space) for body lines, page furniture removed."""
    out = []
    for number in range(max(lo, 1), min(hi, len(pdf_pages)) + 1):
        for raw in pdf_pages[number - 1].splitlines():
            if raw.strip() and not _PDF_FURNITURE.match(raw.strip()):
                out.append((number, raw.strip(), raw.endswith(" ")))
    return out


def _rebuild_from_pdf(
    labels: list[str], following: str | None, path: list[str], pdf_pages: Sequence[str], lo: int, hi: int
) -> list[Unit] | None:
    """Units for `labels` (document order) cut out of the PDF text layer. None if the first
    heading cannot be found."""
    lines = _pdf_lines(pdf_pages, lo, hi)
    starts: dict[str, int] = {}
    cursor = 0
    for label in labels + ([following] if following else []):
        pattern = re.compile(rf"^{re.escape(label)}[ \t]+(?=[A-Z])")
        at = next((k for k in range(cursor, len(lines)) if pattern.match(lines[k][1])), None)
        if at is None:
            if label == labels[0]:
                return None
            continue
        starts[label], cursor = at, at + 1
    ordered = [lab for lab in labels if lab in starts]
    end_all = starts.get(following, len(lines)) if following else len(lines)
    units: list[Unit] = []
    for j, label in enumerate(ordered):
        stop = starts[ordered[j + 1]] if j + 1 < len(ordered) else end_all
        block = lines[starts[label] : stop]
        # The heading may wrap: keep joining while the line ends with a space and the next is not a clause.
        k = 1
        title = block[0][1]
        while k < len(block) and block[k - 1][2] and not block[k][1].startswith("(") and k < 3:
            title += " " + block[k][1]
            k += 1
        unit = Unit(f"s-{label}", list(path), [Line("heading", _collapse(title), block[0][0])], text_source="pdf-text-layer")
        body: list[tuple[int, str]] = []
        for page, group in itertools.groupby(block[k:], key=lambda item: item[0]):
            joined = "\n".join(text for _, text, _ in group)
            unit.notes += [re.sub(r"\s+", " ", m.group(0)).strip() for m in _INLINE_NOTE.finditer(joined)]
            body += [(page, line.strip()) for line in _INLINE_NOTE.sub("", joined).splitlines() if line.strip()]
        for page, text in body:
            prev = unit.atoms[-1] if len(unit.atoms) > 1 else None
            if prev and not _CLAUSE.match(text) and not (prev.text.endswith(_TERMINAL) and text[:1].isupper()):
                unit.atoms[-1] = Line(prev.kind, f"{prev.text} {text}", prev.page)
            else:
                unit.atoms.append(Line("para", text, page))
        units.append(unit)
    return units


def _recover_missing_sections(
    units: list[Unit], pdf_pages: Sequence[str] | None, doc_id: str, warnings: list[str]
) -> list[Unit]:
    out: list[Unit] = []
    for i, unit in enumerate(units):
        following = units[i + 1] if i + 1 < len(units) else None
        missing = _missing_between(unit.sid, following.sid) if following else []
        if not missing:
            out.append(unit)
            continue
        names = [f"{doc_id}:s-{n}" for n in missing]
        if pdf_pages is None:
            unit.contains += names
            out.append(unit)
            warnings.append(
                f"{doc_id}: no heading for section(s) {', '.join(map(str, missing))} after {unit.sid}; no PDF text "
                f"layer given, so that section's chunks are marked as containing them"
            )
            continue
        pages = [a.page for a in unit.atoms if a.page]
        lo = min(pages) if pages else 1
        hi = max([max(pages)] + [a.page for a in following.atoms[:1] if a.page]) if pages else lo
        present = [n for n in missing if _heading_pages(str(n), pdf_pages, lo, hi)]
        gone = [n for n in missing if n not in present]
        if gone:
            warnings.append(f"{doc_id}: section(s) {', '.join(map(str, gone))} have no heading in the PDF either (repealed or omitted)")
        if not present:
            out.append(unit)
            continue
        # 1. cut each missing section out of the converter's own atoms
        trial = Unit(unit.sid, list(unit.path), list(unit.atoms), list(unit.notes))
        cut, current = [], trial
        for n in present:
            piece = _split_at_heading(current, n, pdf_pages, lo, hi)
            if piece is None:
                cut = []
                break
            cut.append(piece)
            current = piece
        if cut:
            out += [trial, *cut]
            continue
        # 2. rebuild the span from the PDF text layer
        labels = [_label(unit.sid), *[str(n) for n in present]]
        rebuilt = _rebuild_from_pdf(labels, _label(following.sid), unit.path, pdf_pages, lo, hi)
        if rebuilt:
            out += rebuilt
            warnings.append(
                f"{doc_id}: rebuilt {', '.join(u.sid for u in rebuilt)} from the PDF text layer (converter lost the headings and text)"
            )
            continue
        unit.contains += [f"{doc_id}:s-{n}" for n in present]
        out.append(unit)
        warnings.append(f"{doc_id}: section(s) {', '.join(map(str, present))} could not be separated from {unit.sid}; its chunks are marked as containing them")
    return out
