from __future__ import annotations

from types import SimpleNamespace

from app.segment_detector import (
    BACK_MATTER,
    CONTENT,
    FRONT_MATTER,
    SegmentBoundaries,
    detect_segments,
)


def _entry(title: str, level: int, target_page: int | None):
    return SimpleNamespace(
        title=title,
        level=level,
        target_page=target_page,
        printed_page=str(target_page) if target_page is not None else None,
    )


def _resolver(toc_pages: set[int], entries: list) -> SimpleNamespace:
    return SimpleNamespace(outline=SimpleNamespace(toc_pages=toc_pages, entries=entries))


def _segments(pages_by_segment: dict[str, set[int]]) -> SegmentBoundaries:
    return SegmentBoundaries(
        front_matter_pages=pages_by_segment.get(FRONT_MATTER, set()),
        content_pages=pages_by_segment.get(CONTENT, set()),
        back_matter_pages=pages_by_segment.get(BACK_MATTER, set()),
    )


def test_no_structure_treats_everything_as_content():
    resolver = _resolver(set(), [])

    boundaries = detect_segments(resolver, 12)

    assert boundaries == _segments(
        {
            FRONT_MATTER: set(),
            CONTENT: set(range(1, 13)),
            BACK_MATTER: set(),
        }
    )


def test_toc_and_chapter_pages_split_front_matter_from_content():
    resolver = _resolver(
        {2},
        [
            _entry("Preface", 1, 3),
            _entry("Introduction", 1, 4),
            _entry("Background", 2, 5),
            _entry("Findings of the review", 1, 7),
            _entry("Glossary", 1, 9),
        ],
    )

    boundaries = detect_segments(resolver, 10)

    # Front matter = TOC page plus everything before the first level-1 entry.
    assert boundaries.front_matter_pages == {1, 2}
    # Back matter = the back-matter TOC destination only.
    assert boundaries.back_matter_pages == {9}
    assert boundaries.content_pages == {3, 4, 5, 6, 7, 8, 10}


def test_classify_maps_pages_to_segments():
    resolver = _resolver(
        {2},
        [
            _entry("Preface", 1, 3),
            _entry("Introduction", 1, 4),
            _entry("Glossary", 1, 9),
        ],
    )

    boundaries = detect_segments(resolver, 10)

    assert boundaries.classify(1) == FRONT_MATTER
    assert boundaries.classify(2) == FRONT_MATTER
    assert boundaries.classify(4) == CONTENT
    assert boundaries.classify(9) == BACK_MATTER


def test_pages_after_last_chapter_matching_back_matter_entry_are_back_matter():
    resolver = _resolver(
        {2},
        [
            _entry("Preface", 1, 3),
            _entry("Introduction", 1, 4),
            _entry("Findings", 1, 7),
            _entry("References", 1, 9),
            _entry("Index", 1, 11),
        ],
    )

    boundaries = detect_segments(resolver, 12)

    # 9 is a back-matter TOC target from the References entry; page 11 is the
    # Index's body destination; pages 10 and 12 match no back-matter entry.
    assert boundaries.back_matter_pages == {9, 11}
    assert 10 not in boundaries.back_matter_pages
    assert 10 in boundaries.content_pages
    assert 12 in boundaries.content_pages