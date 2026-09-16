"""Shared pattern for recovering a footnote's own printed citation number
from its extracted text — used by both exporter.py (deciding whether a
block bundling several citations should split into separate entries) and
preview_html.py (deciding what a footnote's <li value> should be, and
which in-body reference number it should link to). Kept in its own module,
with no other dependencies, so neither file has to import the other just
for this one pattern.
"""

from __future__ import annotations

import re

FOOTNOTE_LEADING_NUMBER_RE = re.compile(r"^\s*(\d{1,4})\s+(.+)$", re.DOTALL)


def resolve_footnote_number(
    text: str, expected: int | None
) -> tuple[str, str] | None:
    """Recover a footnote's own printed citation number from its text,
    same as matching FOOTNOTE_LEADING_NUMBER_RE directly -- except when
    Docling has glued a stray digit onto the very front of the block (a
    real, live extraction artifact: two footnotes sitting on adjacent
    lines at the bottom of a page occasionally get merged into one text
    item, e.g. "3 17 John Chesterman and Brian Galligan, Citizens without
    Rights..." where "17" is the block's real, correct citation number
    and the leading "3" is debris from elsewhere). Matched naively, the
    leading "3" becomes the displayed number and the section's whole
    sequence goes non-monotonic from that one block on, which is exactly
    the symptom the caller's own trustworthy-sequence check exists to
    catch -- but catching it only gets the caller as far as "don't trust
    any number in this section", not the correct one.

    The fix is scoped to the one condition that makes it safe: the
    caller already knows what number should come next in the sequence
    (the previous block's own number, plus one). Only when the naive
    parse disagrees with that expectation AND a second number sitting
    immediately after the first one matches it exactly do we prefer that
    second number instead. A real citation that opens with two numbers
    for legitimate reasons (a case citation continuing "141 410 US 113
    (1973)." where 141 is the correct footnote index and "410 US 113" is
    the reporter volume/page) will not have a second number that happens
    to equal the expected next index, so it is left untouched -- this
    never overrides a first number that already matches what was
    expected, and never fires at all on the first footnote of a section
    (nothing to expect it against yet)."""
    match = FOOTNOTE_LEADING_NUMBER_RE.match(text)
    if not match:
        return None
    number, remainder = match.group(1), match.group(2)
    if expected is not None and int(number) != expected:
        alt = FOOTNOTE_LEADING_NUMBER_RE.match(remainder)
        if alt and int(alt.group(1)) == expected:
            return alt.group(1), alt.group(2)
    return number, remainder
