# How Konverter restores heading levels

**Problem:** Docling's layout model flags a region as a section header but never says *how
deep* that header sits. Every heading therefore arrives at level 1, so a report whose real
structure runs `PART I -> 1. Definitions -> 1.1 Interpretation -> (a)` is a flat stack of
`#` headings. Markdown/DocTags exports, hierarchical chunking and the review outline all
lose the hierarchy.

**Fix:** enable Docling's built-in heading-hierarchy stage. It runs right after reading
order and rewrites `SectionHeaderItem.level` from three signals read out of the document
itself — no extra model, nothing to download. It is disabled by default upstream because a
wrong level is worse than a missing one for pipelines already tuned around flat headings;
Konverter opts in.

## Flow

1. **Configure** — `docling_runner.py::heading_hierarchy_options()` builds
   `HeadingHierarchyOptions` with the documented signals enabled.
2. **Run** — `DocumentConverter.convert()` runs the stage after reading order. Precedence is
   per heading, not per document: PDF bookmarks, then the leading numbering marker, then
   visual style. A confidently bookmark-matched list item is promoted to a section header in
   place; nothing else is added, removed or reordered.
3. **Consume** — the resolved levels reach `pipeline.py` in `raw_docling`. Matched printed-TOC
   headings keep their TOC level; unmatched `section_header` items fall back to Docling's
   level (mapped into the H3–H5 range) in `toc_hierarchy.py::label_for`.

## Options

| Option | Value | Why |
|---|---|---|
| `enabled` | `True` | The whole point: opt in to level inference. |
| `use_bookmarks` | `True` | The PDF outline is the author's own declared hierarchy. |
| `use_numbering` | `True` | Legal/regulatory numbering (`PART I`, `1.1`, `(a)`, `(i)`) is the most reliable signal when there is no outline. |
| `use_style` | `True` | Fallback for headings with neither bookmark nor numbering. |
| `use_font_style` | `True` | Refine the style fallback with weight, slant and all-caps (newer docling). |
| `style_size_tolerance` | `0.05` | Merge near-equal measured sizes so descenders don't invent levels. |
| `max_level` | `5` | Konverter only renders H1–H5; deeper levels are clamped. |
| `bookmark_match_threshold` | `0.76` | Slightly looser than upstream's 0.8 to recover truncated outlines. |

## Version note

`use_font_style` and `style_size_tolerance` were added to `HeadingHierarchyOptions` after
the version pinned in `docling_worker/requirements.txt`. `heading_hierarchy_options()`
introspects the installed option model and drops any field it does not know, so the stage
still runs with its core signals on older pins. Activating the font-style refinement in the
GPU worker means deliberately upgrading that pin and re-running the extraction regression
suite, since the bump also moves `docling-parse` and `docling-ibm-models`.

## Files

`backend/app/docling_runner.py` · tests: `backend/tests/test_docling_runner_options.py`
