from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime
from typing import Any

from .footnote_numbering import FOOTNOTE_LEADING_NUMBER_RE
from .preview_html import build_accessible_html

__all__ = ["build_accessible_html", "build_json_ld", "build_publication"]


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or "section"


def _project_slug(value: str) -> str:
    """Derive the parent project slug from a publication title.

    VLRC publication titles commonly append the publication type after a colon,
    for example ``Project name: Consultation Paper``.  The project page keeps
    only the title before that suffix.
    """
    project_title = re.split(r"\s*:\s*", value.strip(), maxsplit=1)[0]
    project_title = re.sub(
        r"\s+[\-\u2013\u2014]\s+(?:consultation paper|issues paper|final report|report)$",
        "",
        project_title,
        flags=re.IGNORECASE,
    )
    return _slug(project_title)


def _unique_slug(value: str, counts: Counter[str]) -> str:
    base = _slug(value)
    counts[base] += 1
    return base if counts[base] == 1 else f"{base}-{counts[base]}"


def _split_footnote_entries(text: str) -> list[str]:
    """A table of citations converted straight to "footnote" carries one
    citation per line inside a single block's text — every other
    footnote block Docling extracts is already one citation per block,
    and nothing downstream (structured.json, the HTML <ol>, JSON-LD)
    expects one entry to bundle several. Splitting only when each line
    opens with its own strictly-increasing citation number — the same
    trustworthy-sequence signal preview_html.py's _render_footnotes_list
    already uses — avoids splitting a genuine single footnote that
    merely wrapped onto multiple lines."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return [text.strip()]
    matches = [FOOTNOTE_LEADING_NUMBER_RE.match(line) for line in lines]
    numbers = [int(match.group(1)) for match in matches if match]
    trustworthy = len(numbers) == len(lines) and all(
        later > earlier for earlier, later in zip(numbers, numbers[1:])
    )
    return lines if trustworthy else [text.strip()]


def _split_lines(value: str) -> list[str]:
    return [
        re.sub(r"^[•\-–]\s*", "", line).strip()
        for line in value.splitlines()
        if re.sub(r"^[•\-–]\s*", "", line).strip()
    ]


_ORDERED_LIST_MARKER = re.compile(
    r"^(?P<marker>\((?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\)|"
    r"(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)])\s+"
)
_BULLET_LIST_MARKER = re.compile(r"^(?P<marker>[•\-–*·])\s+")


def _parsed_list_entry(value: str) -> dict[str, Any] | None:
    raw = str(value).replace("\t", "  ").strip()
    ordered = _ORDERED_LIST_MARKER.match(raw)
    bullet = _BULLET_LIST_MARKER.match(raw)
    match = ordered or bullet
    marker = match.group("marker") if match else ""
    text = raw[match.end() :].strip() if match else raw
    if not text:
        return None
    marker_number = re.fullmatch(r"\(?(\d+)[.)]", marker)
    return {
        "text": text,
        "marker": marker,
        "enumerated": ordered is not None,
        "level": 0,
        "value": int(marker_number.group(1)) if marker_number else None,
    }


def _section_key(value: str) -> str:
    return (
        re.sub(
            r"^(?:chapter\s+)?\d+\.\s*",
            "",
            value.strip(),
            flags=re.IGNORECASE,
        )
        .strip()
        .casefold()
    )


def _is_chapter_title(value: str) -> bool:
    """Only numbered chapters/parts use collapsible landing navigation."""
    return bool(
        re.match(
            r"^\s*(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b|\d+[.)]\s+)",
            value,
            re.IGNORECASE,
        )
    )


_NUMBERED_CHAPTER_RE = re.compile(r"^(\d+)[.)]\s+(.+)$")

# The same generic front/back-matter names toc_hierarchy.py's own TOC
# parsing (_TOP_LEVEL) already treats as never a numbered chapter —
# reused here so boundary inference (below) never assigns a number to a
# "Preface" or "Glossary" just because it happens to sit next to one, only
# to genuinely chapter-shaped headings like "Introduction" or "Mediation".
_NEVER_A_CHAPTER = re.compile(
    r"^(?:"
    r"preface|foreword|overview|summary|snapshot|key\s+facts?|"
    r"terms?\s+of\s+reference|scope\s+of\s+(?:the\s+)?report|"
    r"glossary(?:\s+of\b.*)?|abbreviations?|acronyms?|"
    r"executive\s+summary|recommendations?|contributors?|"
    r"acknowledg(?:e)?ments?|appendix(?:\s+\w+)?|appendices|"
    r"bibliography|references|index|"
    r"list\s+of\s+(?:figures|tables|recommendations)|"
    r"about\s+the\s+commission"
    r")\s*(?::.*)?$",
    re.IGNORECASE,
)


def _fill_missing_chapter_numbers(sections: list[dict[str, Any]]) -> None:
    """Docling's heading extraction occasionally drops a chapter's own
    number from its title on some runs but not others — "3. Disputes",
    "Community values", "5. Options for reform" — while the printed
    Contents page and every other chapter keep theirs. When an unnumbered
    section sits directly between two numbered chapters, and the count of
    unnumbered sections in the gap exactly matches the numeric gap between
    them, the missing number(s) are unambiguous from position alone —
    independent of whatever Docling did or didn't capture in the title
    text that run. Mutates `sections` in place."""
    numbered = [
        (index, int(match.group(1)))
        for index, section in enumerate(sections)
        if (match := _NUMBERED_CHAPTER_RE.match(str(section.get("displayTitle", ""))))
    ]
    for (index_a, num_a), (index_b, num_b) in zip(numbered, numbered[1:]):
        gap_indexes = list(range(index_a + 1, index_b))
        if gap_indexes and len(gap_indexes) == num_b - num_a - 1:
            for offset, gap_index in enumerate(gap_indexes, start=1):
                gap_section = sections[gap_index]
                if gap_section.get("isChapter"):
                    continue
                title = str(gap_section.get("displayTitle", "")).strip()
                gap_section["displayTitle"] = f"{num_a + offset}. {title}"
                gap_section["isChapter"] = True

    # A gap at the very start or end of the list has no numbered chapter on
    # the far side to confirm the count against — "Introduction" before
    # chapter 3 could just as easily be chapter 1 or 2, or genuinely
    # unnumbered front matter, and the gap count alone can't tell those
    # apart. Only close the walk in one direction at a time, and stop the
    # moment a title matches a name that's never a real chapter (a real
    # "Preface" immediately before "1. Introduction" must stay unnumbered)
    # or the inferred number would reach zero.
    if numbered:
        first_index, first_num = numbered[0]
        number = first_num
        for index in range(first_index - 1, -1, -1):
            title = str(sections[index].get("displayTitle", "")).strip()
            if number <= 1 or _NEVER_A_CHAPTER.match(title) or sections[index].get("isChapter"):
                break
            number -= 1
            sections[index]["displayTitle"] = f"{number}. {title}"
            sections[index]["isChapter"] = True

        last_index, last_num = numbered[-1]
        number = last_num
        for index in range(last_index + 1, len(sections)):
            title = str(sections[index].get("displayTitle", "")).strip()
            if _NEVER_A_CHAPTER.match(title) or sections[index].get("isChapter"):
                break
            number += 1
            sections[index]["displayTitle"] = f"{number}. {title}"
            sections[index]["isChapter"] = True


def _summary_from_values(values: list[str], max_chars: int) -> str:
    """Build a compact description and prefer complete sentences."""
    sentences: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized):
            sentence = sentence.strip()
            key = sentence.casefold()
            if len(sentence) < 35 or key in seen:
                continue
            seen.add(key)
            candidate = " ".join([*sentences, sentence])
            if len(candidate) > max_chars:
                break
            sentences.append(sentence)
        if sentences and len(" ".join(sentences)) >= max_chars * 0.65:
            break
    if sentences:
        return " ".join(sentences)

    normalized = re.sub(r"\s+", " ", " ".join(values)).strip()
    if len(normalized) <= max_chars:
        return normalized
    sentence_end = max(
        normalized.rfind(". ", 0, max_chars),
        normalized.rfind("? ", 0, max_chars),
        normalized.rfind("! ", 0, max_chars),
    )
    if sentence_end >= max_chars // 2:
        return normalized[: sentence_end + 1]
    word_end = normalized.rfind(" ", 0, max_chars - 1)
    return f"{normalized[: max(word_end, max_chars - 2)].rstrip()}…"


def _summary_heading(value: str) -> str:
    value = re.sub(
        r"^\s*(?:(?:chapter|section)\s+)?(?:\d+(?:\.\d+)*|[A-Z])(?:[.):\-–—]|\s)+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _heading_level(label: str) -> int | None:
    match = re.fullmatch(r"section_header_([1-5])", label)
    return int(match.group(1)) if match else None


def _publication_summary(
    blocks: list[dict[str, Any]],
    source_name: str,
    max_chars: int = 600,
) -> str:
    ordered = sorted(
        (block for block in blocks if not block.get("removed")),
        key=lambda value: int(value.get("order", 0)),
    )
    priorities = (
        re.compile(r"^executive summary$"),
        re.compile(r"^summary$"),
        re.compile(r"^scope of report$"),
        re.compile(r"^scope of the report$"),
        re.compile(r"^scope of this report$"),
        re.compile(r"^overview$"),
        re.compile(r"^introduction$"),
    )
    ranked: list[tuple[int, int, int]] = []
    for index, block in enumerate(ordered):
        level = _heading_level(str(block.get("label", "")))
        if level is None:
            continue
        heading = _summary_heading(str(block.get("text", "")))
        for priority, pattern in enumerate(priorities):
            if pattern.fullmatch(heading):
                ranked.append((priority, index, level))
                break

    for _, index, source_level in sorted(ranked):
        candidates: list[str] = []
        for block in ordered[index + 1 :]:
            label = str(block.get("label", ""))
            level = _heading_level(label)
            if level is not None and level <= source_level:
                break
            if label in {"header", "footer", "title", "document_index"}:
                continue
            text = str(block.get("text", "")).strip()
            if label == "text" and len(text) >= 45:
                candidates.append(text)
            for item in block.get("list_items") or []:
                item_text = re.sub(r"^\d+(?:\.\d+)+\s+", "", str(item)).strip()
                if len(item_text) >= 45:
                    candidates.append(item_text)
        if candidates:
            return _summary_from_values(candidates, max_chars)

    fallback = [
        str(block.get("text", "")).strip()
        for block in ordered
        if block.get("label") == "text"
        and len(str(block.get("text", "")).strip()) >= 80
    ]
    if fallback:
        return _summary_from_values(fallback[:3], max_chars)
    return f"This publication presents the reviewed content of {source_name}."


def _format_published_date(value: Any) -> str:
    raw = str(value or "").strip().rstrip(".")
    if not raw:
        return "date not specified"
    normalized = re.sub(
        r"^published\s+(?:on\s+)?",
        "",
        re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE),
        flags=re.IGNORECASE,
    ).strip()
    try:
        parsed_iso = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return f"{parsed_iso.strftime('%B')} {parsed_iso.day}, {parsed_iso.year}"
    except ValueError:
        pass
    for pattern in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
    ):
        try:
            parsed = datetime.strptime(normalized, pattern)
            return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"
        except ValueError:
            continue
    return raw


def _reader_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        section
        for section in sections
        if section.get("id") != "front-matter"
        and str(section.get("displayTitle", "")).strip().casefold()
        not in {"front matter", "contents", "table of contents"}
    ]


def _ordered_reader_sections(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep H1s in printed-contents order and place missing entries by page.

    Most resolved H1s carry a printed-TOC sequence.  Designed front/back matter
    can occasionally lack that field, so a plain ``None -> end`` sort would
    move Preface to the back or detach Appendices from its physical position.
    Missing entries are interpolated between the nearest sequenced page anchors.
    """

    if not sections:
        return []
    original_positions = {id(section): index for index, section in enumerate(sections)}
    anchors = sorted(
        (
            int(section.get("page", 0)),
            float(section["tocSequence"]),
            original_positions[id(section)],
        )
        for section in sections
        if isinstance(section.get("tocSequence"), int)
    )
    if not anchors:
        return list(sections)

    def estimated_sequence(section: dict[str, Any]) -> float:
        sequence = section.get("tocSequence")
        if isinstance(sequence, int):
            return float(sequence)
        page = int(section.get("page", 0))
        before = [anchor for anchor in anchors if anchor[0] <= page]
        after = [anchor for anchor in anchors if anchor[0] > page]
        if not before:
            first_page, first_sequence, _ = anchors[0]
            return first_sequence - 1 - max(0, first_page - page) / 100_000
        if not after:
            last_page, last_sequence, _ = anchors[-1]
            return last_sequence + 1 + max(0, page - last_page) / 100_000
        previous_page, previous_sequence, _ = before[-1]
        next_page, next_sequence, _ = after[0]
        span = max(1, next_page - previous_page)
        fraction = (page - previous_page) / span
        if next_sequence > previous_sequence:
            return previous_sequence + fraction * (
                next_sequence - previous_sequence
            )
        return previous_sequence + 0.5 + fraction / 100

    return sorted(
        sections,
        key=lambda section: (
            estimated_sequence(section),
            int(section.get("page", 0)),
            original_positions[id(section)],
        ),
    )


_BARE_NUM_RE = re.compile(r"^\d{1,4}\s")


def promote_bare_number_markers(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """A numbered item with no punctuation after the number ("1 The
    Registrar should...") isn't recognised as a marker on its own by
    _parsed_list_entry — too easy to confuse with ordinary prose that
    happens to start with a number ("1 in 3 people..."). Requiring every
    item in the list to share this same unpunctuated numbering rules out
    most false positives, but not a bulleted list of *statistics* ("5 per
    cent... 10 per cent... 15 per cent...") — every item still matches, and
    a merely *increasing* run doesn't rule it out either, since ascending
    statistics are common. A genuine numbered list's markers don't just
    increase, they run consecutively — 1, 2, 3, never 5, 10, 15 — which a
    coincidental run of leading numbers is unlikely to do by chance.
    Requiring that is what pipeline.py's own bare-number heuristic
    (_is_footnote_list_block) achieves via a content-vocabulary check —
    this achieves the same rejection with a structural one instead.

    Deliberately requires *every* entry to match, not just most of them —
    a list where bare-numbered top-level items are interleaved with
    already-marked lettered/roman sub-clauses ("(a) allows...", "(i)
    unlawful or") is a different, more common shape handled separately by
    _interleaved_recommendation_numbers below; merging that shape into one
    shared <ol> here would number the sub-clauses as if they were siblings
    of the top-level items instead of their children."""
    if len(entries) < 2:
        return entries
    texts = [str(entry.get("text", "")) for entry in entries]
    matches = [_BARE_NUM_RE.match(text) for text in texts]
    if not all(
        not entry.get("marker") and match for entry, match in zip(entries, matches)
    ):
        return entries
    numbers = [int(text[: match.end()].strip()) for text, match in zip(texts, matches)]
    if any(later != earlier + 1 for earlier, later in zip(numbers, numbers[1:])):
        return entries
    promoted = []
    for entry, text, match in zip(entries, texts, matches):
        assert match is not None
        promoted.append(
            {
                **entry,
                "marker": f"{text[: match.end()].strip()}.",
                "text": text[match.end() :].strip(),
                "enumerated": True,
            }
        )
    return promoted


_DECIMAL_TOP_LEVEL_MARKER_RE = re.compile(r"\(?(\d+)[.)]")


def _interleaved_recommendation_numbers(
    entries: list[dict[str, Any]],
) -> dict[int, tuple[str, str]]:
    """A top-level recommendation number ("1 Victoria should...", or
    already-marked "12.") sitting between its own lettered/roman
    sub-clauses ("(a) allows...", "(i) unlawful or") is not a member of
    one continuous ordered list, even though Docling gives every one of
    these items the same flat level with no nesting signal at all — this
    happens whether the number arrives bare in the entry's own text (no
    marker at all) or already split into a proper marker field, both seen
    across different lists in the same real document. Merging either shape
    into the same <ol> as its sub-items produces an incoherent,
    backwards-jumping visible count: three unvalued sub-items after "13."
    auto-continue the browser's counter to 16, then the next explicit
    "value=14" on the following top-level item snaps it back down —
    exactly the sort of jump a client reviewing "Recommendation 14" right
    after visibly seeing "16" would flag as broken.

    Detected the same way promote_bare_number_markers finds a pure
    bare-number list — a strictly consecutive 1, 2, 3, ... run among
    candidates — except here a candidate can be either an unmarked bare
    number or an already-marked plain decimal marker ("12.", "(12)"; a
    decimal *paragraph* marker like "2.6" never matches this pattern, so
    those keep going through the separate numbered-paragraph path below
    unaffected), and the candidates are expected to sit apart, with
    unrelated sub-clause entries between at least one consecutive pair,
    rather than running as one uninterrupted block ("7." immediately
    followed by "8." is a normal two-item ordered list, not this shape).
    Returns each match's own number and remaining text so the caller can
    render it standalone — the same reader-numbered-paragraph treatment
    already used for decimal paragraph numbers ("2.39 ...") elsewhere in
    this module — instead of forcing it into a shared list counter it was
    never really part of."""
    texts = [str(entry.get("text", "")) for entry in entries]
    markers = [str(entry.get("marker", "")).strip() for entry in entries]
    candidates: dict[int, tuple[str, str]] = {}
    for index, (text, marker) in enumerate(zip(texts, markers)):
        if marker:
            decimal = _DECIMAL_TOP_LEVEL_MARKER_RE.fullmatch(marker)
            if decimal:
                candidates[index] = (decimal.group(1), text.strip())
            continue
        bare = _BARE_NUM_RE.match(text)
        if bare:
            candidates[index] = (text[: bare.end()].strip(), text[bare.end() :].strip())
    if len(candidates) < 2 or len(candidates) == len(entries):
        return {}
    ordered_indexes = sorted(candidates)
    numbers = [int(candidates[index][0]) for index in ordered_indexes]
    if any(later != earlier + 1 for earlier, later in zip(numbers, numbers[1:])):
        return {}
    if all(b - a == 1 for a, b in zip(ordered_indexes, ordered_indexes[1:])):
        return {}
    return dict(candidates)


_ROMAN_NUMERAL_TABLE = (
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
    (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
    (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
)
_ROMAN_NUMERAL_CHARS_RE = re.compile(r"^[ivxlcdm]+$")


def _int_to_roman(value: int) -> str:
    parts = []
    for amount, numeral in _ROMAN_NUMERAL_TABLE:
        count, value = divmod(value, amount)
        parts.append(numeral * count)
    return "".join(parts)


def _roman_to_int(text: str) -> int | None:
    """Only a canonical roman numeral round-trips through _int_to_roman —
    rejects malformed sequences like "iiii" or "vx" that would otherwise
    misread as a valid, if unusual, value."""
    text = text.lower()
    if not text or not _ROMAN_NUMERAL_CHARS_RE.match(text):
        return None
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    previous = 0
    for char in reversed(text):
        value = values[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    if not 0 < total <= 3999 or _int_to_roman(total) != text:
        return None
    return total


_MARKER_CORE_RE = re.compile(r"^\(?([A-Za-z]+|\d+)[.)]?$")


def _marker_candidates(marker: str) -> list[tuple[str, int]]:
    """A marker's own shape can be genuinely ambiguous — "(i)" reads as
    either the letter after "h" in an alpha sequence, or the roman
    numeral 1 starting a fresh sequence — so this returns every valid
    reading rather than picking one; the caller's stack-based sequence
    matching in _next_nesting_level is what actually resolves it, using
    whichever candidate continues (or starts) a real sequence in context."""
    match = _MARKER_CORE_RE.match(marker.strip())
    if not match:
        return []
    core = match.group(1)
    if core.isdigit():
        return [("decimal", int(core))]
    candidates: list[tuple[str, int]] = []
    if len(core) == 1:
        candidates.append(("alpha", ord(core.lower()) - ord("a") + 1))
    roman_value = _roman_to_int(core)
    if roman_value is not None:
        candidates.append(("roman", roman_value))
    return candidates


def _next_nesting_level(
    stack: list[dict[str, Any]],
    marker: str,
) -> tuple[int, str | None, int | None]:
    """Docling gives every sub-clause in a recommendation list the same
    flat level, with no indentation data at all — "1", "(a)", "(b)", "(i)",
    "(ii)" all arrive at level 0. The marker's own shape and its sequence
    relative to markers already seen is the only signal available for
    reconstructing the source document's real outline depth (numeric ->
    lettered -> roman is the standard legal-drafting convention this
    corpus follows throughout).

    `stack` holds one frame per currently open level — its kind (decimal,
    alpha, roman) and last value — and is mutated in place so each call
    sees where the previous marker left off. A marker that continues the
    current top frame's sequence (value + 1, same kind) stays at that
    depth; one that continues an *ancestor* frame's sequence pops back up
    to it (e.g. "(b)" resuming after a nested "(i)(ii)" run under "(a)");
    one that starts fresh at value 1 opens a new, deeper frame as a child
    of whatever was current. Returns (level, kind, value) — kind and value
    are None for an unmatched marker (a bullet, or one this heuristic
    can't place), left at the current depth as a same-level sibling rather
    than guessed at."""
    candidates = _marker_candidates(marker)
    if not candidates:
        return max(0, len(stack) - 1), None, None
    if stack:
        top = stack[-1]
        for kind, value in candidates:
            if kind == top["kind"] and value == top["value"] + 1:
                top["value"] = value
                return len(stack) - 1, kind, value
        for depth in range(len(stack) - 2, -1, -1):
            frame = stack[depth]
            match = next(
                (
                    (kind, value)
                    for kind, value in candidates
                    if kind == frame["kind"] and value == frame["value"] + 1
                ),
                None,
            )
            if match is not None:
                frame["value"] = match[1]
                del stack[depth + 1 :]
                return depth, match[0], match[1]
    start = next((pair for pair in candidates if pair[1] == 1), None)
    if start is not None:
        kind, value = start
        stack.append({"kind": kind, "value": value})
        return len(stack) - 1, kind, value
    if stack:
        return len(stack) - 1, None, None
    kind, value = candidates[0]
    stack.append({"kind": kind, "value": value})
    return 0, kind, value


def _list_publication_blocks(
    block: dict[str, Any],
    page: int,
) -> list[dict[str, Any]]:
    """Preserve ordered markers and numbered paragraphs from Docling lists."""
    entries = block.get("list_entries")
    if not entries:
        source_lines = str(block.get("text", "")).splitlines()
        if not source_lines:
            source_lines = [str(value) for value in block.get("list_items") or []]
        entries = [
            entry
            for value in source_lines
            if (entry := _parsed_list_entry(value)) is not None
        ]
    entries = promote_bare_number_markers(entries)
    interleaved_numbers = _interleaved_recommendation_numbers(entries)
    output: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    pending_style: str | None = None
    pending_start: int | None = None
    # Reset at every flush so unrelated sub-lists (a fresh recommendation's
    # own "(a)(b)..." run, say) never inherit the previous group's nesting
    # state — each pending group starts its outline fresh.
    nesting_stack: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal pending_style, pending_start
        if not pending:
            return
        output.append(
            {
                "type": "list",
                "style": pending_style or "unordered",
                "items": list(pending),
                "start": pending_start,
                "page": page,
            }
        )
        pending.clear()
        pending_style = None
        pending_start = None
        nesting_stack.clear()

    for index, entry in enumerate(entries):
        if index in interleaved_numbers:
            flush()
            number, remaining_text = interleaved_numbers[index]
            output.append(
                {
                    "type": "paragraph",
                    "text": remaining_text,
                    "number": number,
                    "page": page,
                }
            )
            continue
        parsed_text = _parsed_list_entry(str(entry.get("text", "")))
        marker = str(entry.get("marker", "")).strip()
        if marker:
            text = str(entry.get("text", "")).strip()
        elif parsed_text:
            marker = str(parsed_text.get("marker", ""))
            text = str(parsed_text.get("text", ""))
        else:
            text = str(entry.get("text", "")).strip()
        enumerated = bool(entry.get("enumerated")) or bool(
            re.fullmatch(
                r"\((?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\)|"
                r"(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)]",
                marker,
            )
        )
        marker_number = re.fullmatch(r"\(?(\d+)[.)]", marker)
        marker_value = int(marker_number.group(1)) if marker_number else None
        numbered_paragraph = re.match(r"^(\d+(?:\.\d+)+)\s+(.+)$", text, re.DOTALL)
        if numbered_paragraph and not marker:
            flush()
            output.append(
                {
                    "type": "paragraph",
                    "text": numbered_paragraph.group(2),
                    "number": numbered_paragraph.group(1),
                    "page": page,
                }
            )
            continue
        # A decimal-style paragraph number (1.1, 7.2) can also already be
        # sitting in its own marker field — Docling's native list extraction
        # stores it there directly rather than leaving it embedded in text.
        # Without this, an already-correctly-marked numbered paragraph would
        # fall through to a generic ordered list below and lose its real
        # number in favour of plain 1, 2, 3, ... list-position counting.
        if re.fullmatch(r"\d+(?:\.\d+)+", marker):
            flush()
            output.append(
                {
                    "type": "paragraph",
                    "text": text,
                    "number": marker,
                    "page": page,
                }
            )
            continue
        style = "ordered" if enumerated else "unordered"
        raw_level = max(0, int(entry.get("level", 0) or 0))
        marker_kind: str | None = None
        if style == "ordered" and raw_level == 0:
            # Docling gave no real nesting data (every item flat at level
            # 0) — infer outline depth from the marker's own shape instead
            # of trusting a level value that was never meaningful here.
            level, marker_kind, inferred_value = _next_nesting_level(nesting_stack, marker)
            if marker_value is None:
                marker_value = inferred_value
        else:
            level = raw_level
        if pending and level == 0 and pending_style != style:
            flush()
        if pending_style is None:
            pending_style = style
        if style == "ordered" and pending_start is None:
            pending_start = marker_value or 1
        if text:
            pending.append(
                {
                    "text": text,
                    "marker": marker,
                    "level": level,
                    "ordered": enumerated,
                    "value": marker_value,
                    "kind": marker_kind,
                }
            )
    flush()
    return output


def _table_publication_block(
    block: dict[str, Any],
    page: int,
    counts: Counter[str],
) -> dict[str, Any]:
    table = block.get("table_data") or {
        "headers": ["Column 1"],
        "rows": [[str(block.get("text", ""))]],
    }
    rows: list[list[dict[str, Any]]] = []
    headers = list(table.get("headers", []))
    if headers:
        rows.append(
            [
                {
                    "text": str(value),
                    "rowSpan": 1,
                    "colSpan": 1,
                    "columnHeader": True,
                    "rowHeader": False,
                    "startColumn": index,
                }
                for index, value in enumerate(headers)
            ]
        )
    rows.extend(
        [
            [
                {
                    "text": str(value),
                    "rowSpan": 1,
                    "colSpan": 1,
                    "columnHeader": False,
                    "rowHeader": False,
                    "startColumn": index,
                }
                for index, value in enumerate(row)
            ]
            for row in table.get("rows", [])
        ]
    )
    return {
        "type": "table",
        "id": _unique_slug(f"table-{str(block.get('id', ''))}", counts),
        "caption": str(table.get("caption") or block.get("caption") or "").strip(),
        "rows": rows,
        "page": page,
    }


def _lone_bare_numbered_recommendation(
    child: dict[str, Any], box_section_kind: str
) -> tuple[str, str] | None:
    """A recommendations box_section almost always contains exactly one
    list with exactly one item — the panel *is* the single recommendation,
    unlike the document-level "Recommendations" chapter list where many
    numbered items sit consecutively and _interleaved_recommendation_numbers
    can use that run to confirm a bare leading number is really the
    recommendation's own number rather than a coincidence. With only one
    item there's no sequence to compare against, so that check can never
    fire here — and did not, on 96 real instances across 6 documents,
    leaving them to render as a bullet with the number stuck in the text,
    the exact bug already fixed for the document-level case.

    The box's own kind is the substitute signal, and the reason this is
    scoped to "recommendations" specifically rather than every box_section:
    a "case study" or "information" panel's sole bullet could coincidentally
    start with a number ("5 people were interviewed") without being a
    recommendation's own numbering at all — box_section/callout grouping
    (visual_structure.py) only assigns kind "recommendations" when the
    panel's own heading says so (see _callout_kind), so only there is a
    bare leading number on the sole list item reliably that recommendation's
    own number, not a coincidence."""
    if box_section_kind != "recommendations":
        return None
    entries = child.get("list_entries") or []
    if len(entries) != 1:
        return None
    entry = entries[0]
    if entry.get("marker"):
        return None
    text = str(entry.get("text", ""))
    match = _BARE_NUM_RE.match(text)
    if not match:
        return None
    return text[: match.end()].strip(), text[match.end() :].strip()


def _box_section_publication_content(
    block: dict[str, Any],
    page: int,
    counts: Counter[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    box_section_kind = str(block.get("box_section_kind") or "")
    children = block.get("box_section_blocks") or block.get("callout_blocks") or []
    if not children:
        text = str(block.get("text", ""))
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) > 1 and any(
            _ORDERED_LIST_MARKER.match(line.strip())
            or _BULLET_LIST_MARKER.match(line.strip())
            for line in lines
        ):
            return _list_publication_blocks(
                {"text": text, "list_entries": []}, page
            )
        return [
            {"type": "paragraph", "text": value.strip(), "page": page}
            for value in re.split(r"\n\s*\n", text)
            if value.strip()
        ]
    for child in children:
        label = str(child.get("label", "text"))
        child_page = int(child.get("page", page))
        text = str(child.get("text", "")).strip()
        if label in {"list", "list_item"}:
            lone_number = _lone_bare_numbered_recommendation(child, box_section_kind)
            if lone_number is not None:
                number, remaining_text = lone_number
                output.append(
                    {
                        "type": "paragraph",
                        "text": remaining_text,
                        "number": number,
                        "page": child_page,
                    }
                )
                continue
            output.extend(_list_publication_blocks(child, child_page))
        elif label == "table":
            output.append(_table_publication_block(child, child_page, counts))
        elif label == "picture":
            output.append(
                {
                    "type": "figure",
                    "id": _unique_slug(
                        f"figure-{str(child.get('id', ''))}", counts
                    ),
                    "caption": text or "Figure",
                    "page": child_page,
                    "sourceBlockId": str(child.get("id", "")),
                }
            )
        elif label == "footnote":
            for entry_text in _split_footnote_entries(text):
                output.append(
                    {
                        "type": "footnote",
                        "id": _unique_slug(
                            f"box-footnote-{str(child.get('id', ''))}", counts
                        ),
                        "text": entry_text,
                        "page": child_page,
                    }
                )
        elif label.startswith("section_header_"):
            level = min(5, max(1, int(label.rsplit("_", 1)[1])))
            output.append(
                {
                    "type": "heading",
                    "id": _unique_slug(text, counts),
                    "text": text,
                    "level": level,
                    "page": child_page,
                }
            )
        elif label == "formula":
            output.append({"type": "formula", "text": text, "page": child_page})
        elif label == "caption":
            output.append({"type": "caption", "text": text, "page": child_page})
        elif label == "form":
            output.append(
                {
                    "type": "group",
                    "label": "Form fields",
                    "items": [{"text": value} for value in _split_lines(text)],
                    "page": child_page,
                }
            )
        elif text:
            numbered = re.match(r"^(\d+(?:\.\d+)+)\s+(.+)$", text, re.DOTALL)
            output.append(
                {
                    "type": "paragraph",
                    "text": numbered.group(2) if numbered else text,
                    "number": numbered.group(1) if numbered else None,
                    "page": child_page,
                }
            )
    return output


def build_publication(
    blocks: list[dict[str, Any]],
    record: dict[str, Any],
    summary_max_chars: int = 600,
) -> dict[str, Any]:
    blocks = [block for block in blocks if not block.get("removed")]
    counts: Counter[str] = Counter()
    sections: list[dict[str, Any]] = []
    title_blocks = [
        block for block in blocks if block.get("label") == "title" and block.get("text")
    ]
    # record["title"] is reliably populated throughout the whole workflow —
    # the upload-time filename stem before metadata is confirmed, the
    # human-confirmed metadata title after (required before a document can
    # even be approved) — and is what the rest of the app already shows the
    # user everywhere else. Docling's own "title" detection on the page,
    # by contrast, sits right next to a cover page's other large-type
    # elements and picks the wrong one more often than not in this corpus:
    # a National Library CIP catalogue notice, a copyright disclaimer
    # sentence, even a stray contact phone number block, all outrank the
    # real title purely by matching whatever heuristic (font size,
    # position) Docling's layout model used to guess "this looks titular".
    # Preferred here only as a last resort, for the (in practice, never
    # happens) case record["title"] is somehow unset.
    record_title = str(record.get("title") or "").strip()
    source_name = (
        record_title if record_title else str(title_blocks[0]["text"]) if title_blocks else "Document"
    )

    current: dict[str, Any] = {
        "id": "front-matter",
        "title": "Front matter",
        "displayTitle": "Front matter",
        "tocSequence": None,
        "page": 1,
        "blocks": [],
        "headings": [],
        "footnotes": [],
    }
    def finish_current() -> None:
        if (
            current["id"] != "front-matter"
            or current["blocks"]
            or current["footnotes"]
        ):
            if current["id"] != "front-matter":
                first_heading_index = next(
                    (
                        index
                        for index, block in enumerate(current["blocks"])
                        if block.get("type") == "heading"
                    ),
                    -1,
                )
                if first_heading_index >= 0:
                    first_heading = current["blocks"][first_heading_index]
                    if _section_key(str(first_heading.get("text", ""))) == _section_key(
                        str(current["title"])
                    ):
                        current["displayTitle"] = str(
                            first_heading.get("text") or current["displayTitle"]
                        )
                        current["blocks"].pop(first_heading_index)
            previous_level = 1
            for content_block in current["blocks"]:
                if content_block.get("type") != "heading":
                    continue
                requested_level = min(
                    5, max(2, int(content_block.get("level", 2)))
                )
                # Accessible HTML must never skip a heading rank.  Typography
                # and numbering still choose the intended tier, but a missing
                # intermediate source heading is closed up for a valid H1–H5
                # outline.
                content_block["level"] = min(
                    requested_level, previous_level + 1
                )
                previous_level = int(content_block["level"])
            current["headings"] = [
                block for block in current["blocks"] if block.get("type") == "heading"
            ]
            sections.append(current.copy())

    for block in sorted(blocks, key=lambda value: int(value.get("order", 0))):
        label = str(block.get("label", "unspecified"))
        text = str(block.get("text", "")).strip()
        page = int(block.get("page", 1))

        if label == "title" or label in {"header", "footer"}:
            continue

        starts_section = label == "section_header_1"
        if starts_section:
            if current["id"] != "front-matter" and _section_key(text) == _section_key(
                str(current["title"])
            ):
                current["displayTitle"] = text or current["displayTitle"]
                current["page"] = min(page, int(current.get("page", page)))
                continue
            finish_current()
            current = {
                "id": _unique_slug(text or f"section-{len(sections) + 1}", counts),
                "title": text or f"Section {len(sections) + 1}",
                "displayTitle": text or f"Section {len(sections) + 1}",
                "isChapter": _is_chapter_title(text),
                "tocSequence": block.get("toc_sequence"),
                "page": page,
                "blocks": [],
                "headings": [],
                "footnotes": [],
            }
            continue

        if label == "footnote":
            for entry_text in _split_footnote_entries(text):
                current["footnotes"].append(
                    {
                        "id": _unique_slug(
                            f"footnote-{len(current['footnotes']) + 1}", counts
                        ),
                        "text": entry_text,
                        "page": page,
                    }
                )
            continue

        if label.startswith("section_header_"):
            level = min(5, max(1, int(label.rsplit("_", 1)[1])))
            heading = {
                "type": "heading",
                "id": _unique_slug(text, counts),
                "text": text,
                "level": level,
                "page": page,
                "tocSequence": block.get("toc_sequence"),
            }
            current["blocks"].append(heading)
            continue

        if label in {"table", "document_index"}:
            # "document_index" is Docling's own label for any reference-style
            # table (a glossary, a back-of-book alphabetical index, a list
            # of submissions/consultees), not specifically a printed table
            # of contents — a genuine printed TOC is already excluded
            # earlier and more precisely, via is_toc_item()'s page-region
            # matching against the parsed contents pages, before this block
            # even reaches build_publication. Verified directly: every
            # document_index block across all 15 real documents in this
            # project is genuine content (a glossary, an index, a
            # submitter list) — none are an undetected TOC that would
            # duplicate the generated navigation if rendered here too.
            current["blocks"].append(_table_publication_block(block, page, counts))
            continue

        if label in {"box_section", "callout"}:
            current["blocks"].append(
                {
                    "type": "box_section",
                    "id": _unique_slug(
                        f"box-section-{block.get('box_section_title') or block.get('callout_title') or len(current['blocks']) + 1}",
                        counts,
                    ),
                    "title": str(
                        block.get("box_section_title")
                        or block.get("callout_title")
                        or "Box Section"
                    ),
                    "variant": str(
                        block.get("box_section_kind")
                        or block.get("callout_kind")
                        or "information"
                    ),
                    "blocks": _box_section_publication_content(block, page, counts),
                    "page": page,
                }
            )
            continue

        if label in {"list", "list_item"}:
            current["blocks"].extend(_list_publication_blocks(block, page))
            continue

        if label == "picture":
            current["blocks"].append(
                {
                    "type": "figure",
                    "id": _unique_slug(f"figure-{len(current['blocks']) + 1}", counts),
                    "caption": text or "Figure",
                    "page": page,
                    "sourceBlockId": str(block.get("id", "")),
                }
            )
            continue

        if label == "caption":
            current["blocks"].append({"type": "caption", "text": text, "page": page})
            continue

        if label == "quote":
            quote = {"type": "quote", "text": text, "page": page}
            attribution = str(block.get("quote_attribution") or "").strip()
            # Do not resurrect an attribution removed or changed by the reviewer.
            if attribution and text.rstrip().endswith(attribution):
                quote["text"] = text.rstrip()[:-len(attribution)].rstrip(" \n—–")
                quote["attribution"] = attribution
            current["blocks"].append(quote)
            continue

        if label == "form":
            current["blocks"].append(
                {
                    "type": "group",
                    "label": "Form fields",
                    "items": [{"text": value} for value in _split_lines(text)],
                    "page": page,
                }
            )
            continue

        if label == "formula":
            current["blocks"].append(
                {
                    "type": "formula",
                    "text": text,
                    "page": page,
                }
            )
            continue

        numbered = re.match(r"^(\d+(?:\.\d+)+)\s+(.+)$", text, re.DOTALL)
        current["blocks"].append(
            {
                "type": "paragraph",
                "text": numbered.group(2) if numbered else text,
                "number": numbered.group(1) if numbered else None,
                "page": page,
            }
        )

    finish_current()
    reader_sections = _ordered_reader_sections(_reader_sections(sections))
    _fill_missing_chapter_numbers(reader_sections)
    if not reader_sections:
        fallback = next(
            (
                section
                for section in sections
                if section.get("blocks") or section.get("footnotes")
            ),
            None,
        )
        if fallback:
            reader_sections = [
                {
                    **fallback,
                    "id": "document-body",
                    "title": "Document",
                    "displayTitle": "Document",
                }
            ]

    stats = {
        "pages": int(record.get("pages", 0)),
        "textItems": sum(
            1
            for block in blocks
            if block.get("label")
            in {
                "text",
                "title",
                "caption",
                "footnote",
                "formula",
                "box_section",
                "callout",
                "section_header_1",
                "section_header_2",
                "section_header_3",
                "section_header_4",
                "section_header_5",
            }
        ),
        "tables": sum(
            1 for block in blocks if block.get("label") in {"table", "document_index"}
        ),
        "pictures": sum(1 for block in blocks if block.get("label") == "picture"),
        # One "footnote"-labeled block can hold several citations bundled
        # onto separate lines (see _split_footnote_entries) and becomes
        # several entries in a section's footnotes list — counting blocks
        # 1:1 undercounts against what actually gets exported.
        "footnotes": sum(
            len(_split_footnote_entries(str(block.get("text", "")).strip()))
            for block in blocks
            if block.get("label") == "footnote"
        ),
    }
    return {
        "schemaName": "Konverter accessible document",
        "schemaVersion": "1.0",
        "sourceName": source_name,
        "sourceFile": str(record.get("file_name", "source.pdf")),
        "summary": [_publication_summary(blocks, source_name, summary_max_chars)],
        "sections": reader_sections,
        "stats": stats,
    }


def _iso_published_date(value: Any) -> str | None:
    """Normalise the reviewed date to ISO 8601 (YYYY[-MM[-DD]]) when possible."""
    raw = re.sub(
        r"^published\s+(?:on\s+)?",
        "",
        str(value or "").strip().rstrip("."),
        flags=re.IGNORECASE,
    )
    raw = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE).strip()
    if not raw:
        return None
    if re.fullmatch(
        r"(?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?", raw
    ):
        return raw
    for pattern, formatter in (
        ("%Y-%m-%d", "%Y-%m-%d"),
        ("%Y/%m/%d", "%Y-%m-%d"),
        ("%d/%m/%Y", "%Y-%m-%d"),
        ("%d-%m-%Y", "%Y-%m-%d"),
        ("%d.%m.%Y", "%Y-%m-%d"),
        ("%d %B %Y", "%Y-%m-%d"),
        ("%d %b %Y", "%Y-%m-%d"),
        ("%B %d, %Y", "%Y-%m-%d"),
        ("%B %d %Y", "%Y-%m-%d"),
        ("%b %d, %Y", "%Y-%m-%d"),
        ("%B %Y", "%Y-%m"),
        ("%b %Y", "%Y-%m"),
    ):
        try:
            return datetime.strptime(raw, pattern).strftime(formatter)
        except ValueError:
            continue
    return None


def _split_values(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


ISBN_PATTERN = re.compile(
    r"\bISBNs?\b[:\s]*([0-9][0-9\- ]{7,20}[0-9Xx])", re.IGNORECASE
)
ISSN_PATTERN = re.compile(r"\bISSN\b[:\s]*([0-9]{4}-?[0-9]{3}[0-9Xx])", re.IGNORECASE)
SERIES_PATTERN = re.compile(r"^Series:\s*(.+)$", re.IGNORECASE)


def _citation_entry(value: str) -> Any:
    """Type legislation and case citations so downstream AI can use them."""
    if re.search(r"\bAct\s+(?:19|20)\d{2}\b", value):
        return {"@type": "Legislation", "name": value}
    if re.search(r"\b\S+\s+v\s+\S+", value):
        return {"@type": "CreativeWork", "name": value}
    return value


def _prune(node: dict[str, Any]) -> dict[str, Any]:
    """Omit properties whose values are unknown rather than guessing."""
    return {
        key: value for key, value in node.items() if value not in (None, "", [], {})
    }


def _accessibility_properties(publication: dict[str, Any]) -> dict[str, Any]:
    """Claim only the accessibility the generated HTML actually provides.

    The exported page always contains images (cover, logo) with alt text and
    offers structural navigation, so those claims are constant. Text
    sufficiency and the alternativeText claim depend on every figure in this
    particular document carrying a caption (which becomes its alt text).
    """
    def figures_in(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        figures: list[dict[str, Any]] = []
        for block in blocks:
            if block.get("type") == "figure":
                figures.append(block)
            children = block.get("blocks")
            if isinstance(children, list):
                figures.extend(figures_in(children))
        return figures

    figures = [
        figure
        for section in publication.get("sections", [])
        for figure in figures_in(section.get("blocks", []))
    ]
    all_figures_captioned = all(str(f.get("caption", "")).strip() for f in figures)
    features = ["structuralNavigation", "tableOfContents", "readingOrder"]
    if all_figures_captioned:
        features.append("alternativeText")
    summary = (
        "This HTML edition provides structural navigation, a table of contents, "
        "a defined reading order and alternative text for figures."
        if all_figures_captioned
        else "This HTML edition provides structural navigation, a table of contents "
        "and a defined reading order. Some figures may not include source-supplied "
        "alternative text."
    )
    return {
        "accessMode": ["textual", "visual"],
        "accessModeSufficient": [{"@type": "ItemList", "itemListElement": ["textual"]}]
        if all_figures_captioned
        else None,
        "accessibilityFeature": features,
        "accessibilityHazard": [
            "noFlashingHazard",
            "noMotionSimulationHazard",
            "noSoundHazard",
        ],
        "accessibilitySummary": summary,
    }


def build_json_ld(
    document_id: str,
    publication: dict[str, Any],
    metadata: dict[str, Any],
    *,
    site_url: str = "",
    site_name: str = "",
    page_url_template: str = "",
    public_api_url: str = "",
    license_url: str = "",
    copyright_holder: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Schema.org graph combining document metadata with page/site context.

    Generation rules:
    - Node ids are page-specific: with KONVERTER_PAGE_URL_TEMPLATE configured
      the WebPage/breadcrumb ids are absolute URLs; otherwise they are
      document-scoped fragments that resolve against the hosting URL.
    - The WebSite describes the hosting site (KONVERTER_SITE_URL/_NAME). The
      document's publisher is linked as site owner only when the configured
      site name matches the publisher; hosting elsewhere leaves them separate.
    - The report's own datePublished stays distinct from the generated page's
      datePublished/dateModified (the approval timestamp).
    - author is only emitted when the source identifies one (the current
      metadata schema has no author field, so it is omitted).
    - citation carries only the human-confirmed citation list; ISBN/ISSN move
      to identifier and a series statement becomes isPartOf/reportNumber.
    - Unknown values are omitted, never guessed.
    """
    publishers = _split_values(metadata.get("publisher"))
    jurisdictions = _split_values(metadata.get("jurisdiction"))
    authors = _split_values(metadata.get("authors"))
    raw_date = str(metadata.get("published_date") or "").strip()
    title = str(metadata.get("title") or publication.get("sourceName") or "").strip()
    report_id = f"urn:uuid:{document_id}"
    api_root = (
        f"{public_api_url.rstrip('/')}/api/documents/{document_id}"
        if public_api_url
        else f"/api/documents/{document_id}"
    )
    html_url = f"{api_root}/exports/accessible.html"
    source_url = f"{api_root}/source"
    cover_url = f"{api_root}/cover"

    page_url = ""
    if page_url_template:
        page_url = page_url_template.replace(
            "{slug}", _slug(title) or document_id
        ).replace("{id}", document_id)
    page_id = page_url or f"#webpage-{document_id}"
    breadcrumb_id = (
        f"{page_url}#breadcrumb" if page_url else f"#breadcrumb-{document_id}"
    )
    image_id = (
        f"{page_url}#primaryimage"
        if page_url
        else f"#primaryimage-{document_id}"
    )

    citations: list[Any] = []
    identifiers: list[dict[str, Any]] = []
    series_name: str | None = None
    report_number: str | None = None
    for value in _split_values(metadata.get("citations")):
        isbn = ISBN_PATTERN.search(value)
        issn = ISSN_PATTERN.search(value)
        series = SERIES_PATTERN.match(value)
        if isbn:
            identifiers.append(
                {
                    "@type": "PropertyValue",
                    "propertyID": "ISBN",
                    "value": isbn.group(1).strip(),
                }
            )
        elif issn:
            identifiers.append(
                {
                    "@type": "PropertyValue",
                    "propertyID": "ISSN",
                    "value": issn.group(1).strip(),
                }
            )
        elif series:
            statement = series.group(1).strip()
            numbered = re.fullmatch(r"(.+?)[\s,]+(?:no\.?\s*)?(\d+)", statement)
            if numbered:
                series_name, report_number = (
                    numbered.group(1).strip(),
                    numbered.group(2),
                )
            else:
                series_name = statement
        else:
            citations.append(_citation_entry(value))

    site_is_owner = bool(
        site_url
        and site_name
        and publishers
        and site_name.strip().lower() == publishers[0].strip().lower()
    )
    organisation_nodes = [
        _prune(
            {
                "@type": "Organization",
                "@id": (
                    f"{site_url}/#organization"
                    if site_is_owner and index == 0
                    else f"#organization-{document_id}"
                    + ("" if index == 0 else f"-{index + 1}")
                ),
                "name": value,
                "url": f"{site_url}/" if site_is_owner and index == 0 else None,
            }
        )
        for index, value in enumerate(publishers)
    ]
    organisation_refs = [{"@id": node["@id"]} for node in organisation_nodes]
    holder_ref: dict[str, str] | None = None
    if copyright_holder:
        matching_holder = next(
            (
                node
                for node in organisation_nodes
                if str(node.get("name", "")).strip().casefold()
                == copyright_holder.strip().casefold()
            ),
            None,
        )
        if matching_holder is not None:
            holder_ref = {"@id": str(matching_holder["@id"])}
        else:
            holder_node = {
                "@type": "Organization",
                "@id": f"#copyright-holder-{document_id}",
                "name": copyright_holder,
            }
            organisation_nodes.append(holder_node)
            holder_ref = {"@id": holder_node["@id"]}

    description = " ".join(
        str(value).strip()
        for value in publication.get("summary", [])
        if str(value).strip()
    )
    language = (
        "en-AU"
        if any("australia" in value.lower() for value in jurisdictions)
        else "en"
    )

    report = _prune(
        {
            "@type": "Report",
            "@id": report_id,
            "name": title,
            "description": description or None,
            "inLanguage": language,
            # Only present when the source metadata identifies authors.
            "author": [{"@type": "Person", "name": value} for value in authors],
            "publisher": organisation_refs,
            "datePublished": _iso_published_date(raw_date) or raw_date or None,
            "license": license_url or None,
            "copyrightHolder": holder_ref,
            "reportNumber": report_number,
            "isPartOf": {"@type": "CreativeWorkSeries", "name": series_name}
            if series_name
            else None,
            "identifier": identifiers,
            "spatialCoverage": [
                {"@type": "AdministrativeArea", "name": value}
                for value in jurisdictions
            ],
            "citation": citations,
            "isAccessibleForFree": True,
            **_accessibility_properties(publication),
            "encoding": [
                {
                    "@type": "MediaObject",
                    "encodingFormat": "application/pdf",
                    "contentUrl": source_url,
                },
                {
                    "@type": "MediaObject",
                    "encodingFormat": "text/html",
                    "contentUrl": html_url,
                },
            ],
            "image": {"@id": image_id},
            "mainEntityOfPage": {"@id": page_id},
            "hasPart": [
                _prune(
                    {
                    "@type": "Chapter",
                    "@id": f"{report_id}#{section['id']}",
                    "isPartOf": {"@id": report_id},
                    "name": section["displayTitle"],
                    "position": index + 1,
                    "url": f"{page_url}#{section['id']}" if page_url else None,
                    }
                )
                for index, section in enumerate(publication.get("sections", []))
            ],
        }
    )

    web_page = _prune(
        {
            "@type": "WebPage",
            "@id": page_id,
            "url": page_url or None,
            "name": f"{title} - {site_name}" if site_name else title,
            "mainEntity": {"@id": report_id},
            "isPartOf": {"@id": f"{site_url}/#website"} if site_url else None,
            "breadcrumb": {"@id": breadcrumb_id} if site_url else None,
            "inLanguage": language,
            "datePublished": generated_at,
            "dateModified": generated_at,
            "primaryImageOfPage": {"@id": image_id},
            "potentialAction": [
                {"@type": "ReadAction", "target": [page_url or html_url]}
            ],
        }
    )

    image_node = {
        "@type": "ImageObject",
        "@id": image_id,
        "url": cover_url,
        "contentUrl": cover_url,
        "encodingFormat": "image/png",
        "caption": f"Cover of {title}",
        "representativeOfPage": True,
    }
    graph: list[dict[str, Any]] = [
        report,
        web_page,
        image_node,
        *organisation_nodes,
    ]
    if site_url:
        graph.append(
            _prune(
                {
                    "@type": "WebSite",
                    "@id": f"{site_url}/#website",
                    "url": f"{site_url}/",
                    "name": site_name or None,
                    "publisher": organisation_refs[:1] if site_is_owner else None,
                    "inLanguage": language,
                }
            )
        )
        graph.append(
            {
                "@type": "BreadcrumbList",
                "@id": breadcrumb_id,
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "Home",
                        "item": f"{site_url}/",
                    },
                    {"@type": "ListItem", "position": 2, "name": title},
                ],
            }
        )

    return {"@context": "https://schema.org", "@graph": graph}


