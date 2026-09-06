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
