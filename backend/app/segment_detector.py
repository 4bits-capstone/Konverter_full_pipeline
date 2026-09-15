"""Document segment detection: front matter, main content, back matter.

Uses heuristic signals from the TOC outline and chapter pages to classify
blocks into one of three segments. The classification is page-based:
blocks on pages within the same segment share the same label.

Signals used:
- TOC pages (from TocHierarchyResolver.outline.toc_pages) → front matter
- ChapterPage list → chapter boundaries
- Pages after last chapter → back matter
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .toc_hierarchy import ChapterPage, TocHierarchyResolver


FRONT_MATTER = "front_matter"
CONTENT = "content"
BACK_MATTER = "back_matter"

_BACK_MATTER_MARKERS = (
    "appendices",
    "appendix",
    "bibliography",
    "references",
    "index",
    "glossary",
    "acknowledgements",
    "acknowledgments",
)


@dataclass
class SegmentBoundaries:
    """Page ranges for each document segment."""

    front_matter_pages: set[int]
    content_pages: set[int]
    back_matter_pages: set[int]

    def classify(self, page: int) -> str:
        if page in self.front_matter_pages:
            return FRONT_MATTER
        if page in self.back_matter_pages:
            return BACK_MATTER
        return CONTENT


def detect_segments(
    resolver: TocHierarchyResolver,
    total_pages: int,
) -> SegmentBoundaries:
    """Detect segment boundaries using TOC and chapter data.

    Strategy:
    1. Front matter = pages before the first chapter page AND all TOC pages
    2. Content = pages from first chapter to last chapter
    3. Back matter = pages after last chapter, or pages with back-matter TOC entries
    """
    toc_pages = resolver.outline.toc_pages or set()
    entries = resolver.outline.entries or []

    # Find chapter entries from TOC (level 1 entries that are chapters)
    chapter_pages = _find_chapter_pages(entries, resolver)

    # Find back matter entries from TOC
    back_matter_toc_pages = _find_back_matter_pages(entries)

    if not chapter_pages and not toc_pages:
        # No structure detected - treat everything as content
        return SegmentBoundaries(
            front_matter_pages=set(),
            content_pages=set(range(1, total_pages + 1)),
            back_matter_pages=set(),
        )

    # Determine first and last chapter pages
    first_chapter_page = min(chapter_pages) if chapter_pages else None
    last_chapter_page = max(chapter_pages) if chapter_pages else None

    front_matter_pages: set[int] = set()
    content_pages: set[int] = set()
    back_matter_pages: set[int] = set()

    # Front matter: all TOC pages + pages before first chapter
    front_matter_pages.update(toc_pages)
    if first_chapter_page is not None:
        for page in range(1, first_chapter_page):
            if page not in toc_pages:
                front_matter_pages.add(page)

    # Back matter: pages with back-matter TOC entries + pages after last chapter
    back_matter_pages.update(back_matter_toc_pages)
    if last_chapter_page is not None:
        for page in range(last_chapter_page + 1, total_pages + 1):
            if page not in back_matter_toc_pages:
                # Check if this page is clearly back matter
                if _is_back_matter_page(page, resolver):
                    back_matter_pages.add(page)

    # Content: everything not front or back
    for page in range(1, total_pages + 1):
        if page not in front_matter_pages and page not in back_matter_pages:
            content_pages.add(page)

    return SegmentBoundaries(
        front_matter_pages=front_matter_pages,
        content_pages=content_pages,
        back_matter_pages=back_matter_pages,
    )


def _find_chapter_pages(
    entries: list[Any],
    resolver: TocHierarchyResolver,
) -> list[int]:
    """Find pages that contain chapter-level headings from TOC entries."""
    chapter_pages: list[int] = []
    for entry in entries:
        if entry.level == 1 and entry.target_page is not None:
            chapter_pages.append(entry.target_page)
    return sorted(set(chapter_pages))


def _find_back_matter_pages(entries: list[Any]) -> set[int]:
    """Find pages referenced by back-matter TOC entries."""
    pages: set[int] = set()
    for entry in entries:
        if entry.level == 1 and entry.target_page is not None:
            title_lower = entry.title.lower().strip()
            if any(marker in title_lower for marker in _BACK_MATTER_MARKERS):
                pages.add(entry.target_page)
    return pages


def _is_back_matter_page(page: int, resolver: TocHierarchyResolver) -> bool:
    """Heuristic: is this page likely back matter?

    Uses TOC entries to check if the page is associated with a back-matter
    section. Falls back to checking if the page is beyond the last chapter.
    """
    for entry in resolver.outline.entries:
        if entry.target_page == page:
            title_lower = entry.title.lower().strip()
            if any(marker in title_lower for marker in _BACK_MATTER_MARKERS):
                return True
    return False
