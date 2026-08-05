from __future__ import annotations

import html
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .config import Settings
from .hierarchy_integration import apply_hierarchy, attach_hierarchy_metadata
from .metadata_rules import empty_metadata_payload, extract_metadata_from_docling
from .visual_structure import (
    annotate_pdf_artifacts,
    detect_callout_regions,
    group_visual_callouts,
)

StageCallback = Callable[[int, str], None]


LABEL_DISPLAY = {
    "box_section": "Box Section",
    "caption": "Caption",
    "chapter_title": "Chapter title",
    "document_index": "Document index",
    "footnote": "Footnote",
    "footer": "Footer",
    "form": "Form",
    "formula": "Formula",
    "header": "Header",
    "list": "List",
    "picture": "Picture",
    "section_header_1": "H1",
    "section_header_2": "H2",
    "section_header_3": "H3",
    "section_header_4": "H4",
    "section_header_5": "H5",
    "table": "Table",
    "title": "Title",
    "text": "Text",
    "unspecified": "Unspecified",
}

RAW_LABEL_MAP = {
    "box_section": "box_section",
    "caption": "caption",
    "callout": "box_section",
    "checkbox_selected": "form",
    "checkbox_unselected": "form",
    "document_index": "document_index",
    "footnote": "footnote",
    "formula": "formula",
    "list": "list",
    "list_item": "list",
    "page_footer": "footer",
    "page_header": "header",
    "picture": "picture",
    "section_header": "section_header_1",
    "table": "table",
    "title": "title",
    "text": "text",
    "unspecified": "unspecified",
}


def _effective_raw_label(item: dict[str, Any]) -> str:
    """Return the source label while retaining validated header demotions.

    The hierarchy postprocessor can promote numbered Docling list items.  Legal
    footnotes also start with numbers, so treating every promotion as a heading
    turns citations into H2/H3 elements.  Restore Docling's original list label;
    the chapter-outline resolver can still promote a matching entry explicitly.
    """
    raw = str(item.get("label", "unspecified")).lower()
    metadata = item.get("meta") or {}
    original = str(metadata.get("konverter_original_label", "")).lower()
    if (
        raw == "text"
        and original == "section_header"
        and isinstance(metadata.get("hf__heading_level"), int)
    ):
        return "section_header"
    if original:
        return original
    return raw


class DoclingHierarchyResolver:
    """Rebase package hierarchy into Konverter's chapter/H1-H5 contract.

    This adapter does not promote ordinary text or infer headings from wording.
    It only turns the levels already emitted by ``docling-hierarchical-pdf``
    into the structure required by the preview and accessible HTML.
    """

    def __init__(
        self,
        main_title_ref: str | None,
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> None:
        self.main_title_ref = main_title_ref
        self.chapter_level: int | None = None
        self.current_chapter_level: int | None = None

        heading_levels: list[int] = []
        title_level: int | None = None
        for reference in ordered_references:
            item = all_items.get(reference)
            if not item or str(item.get("label", "")).lower() != "section_header":
                continue
            level = self._package_level(item)
            if level is None:
                continue
            if reference == main_title_ref:
                title_level = level
            else:
                heading_levels.append(level)

        if title_level is not None:
            descendants = [level for level in heading_levels if level > title_level]
            if descendants:
                self.chapter_level = min(descendants)
        if self.chapter_level is None and heading_levels:
            self.chapter_level = min(heading_levels)

    @staticmethod
    def _package_level(item: dict[str, Any]) -> int | None:
        metadata = item.get("meta") or {}
        level = metadata.get("hf__heading_level", item.get("level"))
        return min(5, max(1, level)) if isinstance(level, int) else None

    def label_for(self, item: dict[str, Any]) -> str:
        reference = str(item.get("self_ref", ""))
        if reference == self.main_title_ref:
            self.current_chapter_level = None
            return "title"

        raw = str(item.get("label", "unspecified")).lower()
        if raw == "section_header":
            level = self._package_level(item) or 1
            if self.chapter_level is not None and level <= self.chapter_level:
                self.current_chapter_level = level
                return "chapter_title"
            base = self.current_chapter_level
            if base is None:
                base = self.chapter_level if self.chapter_level is not None else level - 1
            return f"section_header_{min(5, max(1, level - base))}"
        return RAW_LABEL_MAP.get(raw, "unspecified")

    @staticmethod
    def is_chapter_contents(reference: str) -> bool:
        return False

    @staticmethod
    def is_chapter_context(reference: str) -> bool:
        return False


def _first_page(item: dict[str, Any]) -> int:
    provenance = item.get("prov") or []
    return int(provenance[0].get("page_no", 1)) if provenance else 1


def _plain_text_from_table(table: dict[str, Any] | None) -> str:
    if not table:
        return ""
    rows = []
    headers = [str(value).strip() for value in table.get("headers", [])]
    if any(headers):
        rows.append(" | ".join(headers))
    rows.extend(
        " | ".join(str(value).strip() for value in row) for row in table.get("rows", [])
    )
    return "\n".join(value for value in rows if value.strip(" |"))


class HeadingResolver:
    """Resolve headings from chapter opening pages before falling back to style."""

    def __init__(
        self,
        main_title_ref: str | None,
        all_items: dict[str, dict[str, Any]] | None = None,
        ordered_references: list[str] | None = None,
        page_sizes: dict[int, tuple[float, float]] | None = None,
    ) -> None:
        self.main_title_ref = main_title_ref
        self.page_sizes = page_sizes or {}
        self._layout_chapters_resolved = False
        self.current_chapter_key = ""
        self.current_outline: set[str] = set()
        self.chapter_outlines: dict[str, set[str]] = {}
        self.chapter_title_refs: set[str] = set()
        self.chapter_title_continuation_refs: set[str] = set()
        self.chapter_contents_refs: set[str] = set()
        self.chapter_context_refs: set[str] = set()
        self.chapter_h1_refs: set[str] = set()
        self.chapter_key_by_ref: dict[str, str] = {}
        self.chapter_title_text_by_ref: dict[str, str] = {}
        self.forced_heading_levels: dict[str, int] = {}
        self.lower_level_by_size: dict[float, int] = {}
        self.h2_font_floor: float | None = None
        self._hierarchy_base_level: int | None = None
        self._pending_split_chapter_page: int | None = None
        # Last emitted heading level, used to prevent skipped levels
        # (e.g. an H4 directly after a chapter title) in the nested output.
        self._last_heading_level = 1
        if all_items is not None and ordered_references is not None:
            self._discover_chapter_outlines(all_items, ordered_references)
            self._build_lower_style_levels(all_items)

    def label_for(self, item: dict[str, Any]) -> str:
        raw = _effective_raw_label(item)
        reference = str(item.get("self_ref", ""))
        text = str(item.get("text", "")).strip()

        if reference == self.main_title_ref:
            self._last_heading_level = 1
            return "title"

        if reference in self.chapter_title_continuation_refs:
            self._last_heading_level = 1
            return "chapter_title_continuation"

        if reference in self.chapter_h1_refs:
            chapter_key = self.chapter_key_by_ref.get(reference) or self._chapter_key(
                text
            )
            if chapter_key and chapter_key != self.current_chapter_key:
                self._select_chapter_key(chapter_key, item)
            else:
                self._set_hierarchy_base(item)
            self._last_heading_level = 1
            return "section_header_1"

        if reference in self.chapter_title_refs:
            self._select_chapter_key(
                self.chapter_key_by_ref.get(reference) or self._chapter_key(text),
                item,
            )
            self._last_heading_level = 1
            return "chapter_title"

        forced_level = self.forced_heading_levels.get(reference)
        if forced_level is not None:
            self._last_heading_level = forced_level
            return f"section_header_{forced_level}"

        if self._pending_split_chapter_page is not None:
            pending_page = self._pending_split_chapter_page
            self._pending_split_chapter_page = None
            if _first_page(item) == pending_page and text:
                self.current_chapter_key = self._chapter_key(text)
                self.current_outline = self.chapter_outlines.get(
                    self.current_chapter_key, set()
                )
                self._last_heading_level = 1
                return "chapter_title_continuation"

        chapter_key = self._chapter_key(text)
        if self.current_chapter_key and chapter_key == self.current_chapter_key:
            self._set_hierarchy_base(item)
            self._last_heading_level = 1
            return "section_header_1"
        if chapter_key in self.current_outline and self._can_promote_outline_item(
            item
        ):
            self._last_heading_level = 2
            return "section_header_2"
        if (
            self.current_chapter_key == "appendices"
            and re.match(r"^appendix\s+[a-z0-9ivxlcdm]+\b", text, re.IGNORECASE)
            and self._can_promote_outline_item(item)
        ):
            self._last_heading_level = 2
            return "section_header_2"

        if raw == "title":
            # ``Title`` is reserved for the single document title.  A later
            # Docling title becomes a chapter only when discovery has already
            # confirmed it from chapter-layout or repeated-heading evidence.
            return "section_header_2" if self.current_chapter_key else "text"

        if raw != "section_header":
            return RAW_LABEL_MAP.get(raw, "unspecified")

        if self._is_citation_like(text, item):
            return "list"

        if self._layout_chapters_resolved:
            inferred = self._infer_lower_level(item)
            level = max(2, min(inferred, self._last_heading_level + 1, 5))
            self._last_heading_level = level
            return f"section_header_{level}"

        if not self.current_chapter_key and (
            self._is_numbered_chapter(text) or self._is_named_back_matter_chapter(text)
        ):
            self._select_chapter(text, item)
            self._last_heading_level = 1
            return "chapter_title"
        if self._is_numbered_chapter(text) and chapter_key != self.current_chapter_key:
            self._select_chapter(text, item)
            self._last_heading_level = 1
            return "chapter_title"
        if (
            self._is_named_back_matter_chapter(text)
            and chapter_key != self.current_chapter_key
        ):
            self._select_chapter(text, item)
            self._last_heading_level = 1
            return "chapter_title"

        inferred = self._infer_lower_level(item)
        level = max(2, min(inferred, self._last_heading_level + 1, 5))
        self._last_heading_level = level
        return f"section_header_{level}"

    def is_chapter_contents(self, reference: str) -> bool:
        return reference in self.chapter_contents_refs

    def is_chapter_context(self, reference: str) -> bool:
        """Return true for a repeated ``Chapter N`` page label, not a new section."""
        return reference in self.chapter_context_refs

    def is_forced_structure(self, reference: str) -> bool:
        return reference in (
            self.chapter_title_refs
            | self.chapter_title_continuation_refs
            | self.chapter_h1_refs
        ) or reference in self.forced_heading_levels or reference == self.main_title_ref

    def output_text(self, item: dict[str, Any]) -> str:
        reference = str(item.get("self_ref", ""))
        return self.chapter_title_text_by_ref.get(
            reference,
            str(item.get("text", "")).strip(),
        )

    def _select_chapter(
        self,
        text: str,
        item: dict[str, Any] | None = None,
    ) -> None:
        self._select_chapter_key(self._chapter_key(text), item)
        self._pending_split_chapter_page = (
            _first_page(item)
            if item is not None
            and re.fullmatch(
                r"chapter\s+\d+[.:)]?",
                text.strip(),
                re.IGNORECASE,
            )
            else None
        )

    def _select_chapter_key(
        self,
        chapter_key: str,
        item: dict[str, Any] | None = None,
    ) -> None:
        self.current_chapter_key = chapter_key
        self.current_outline = self.chapter_outlines.get(
            self.current_chapter_key, set()
        )
        self._hierarchy_base_level = None
        self._pending_split_chapter_page = None
        if item is not None and _effective_raw_label(item) == "section_header":
            self._set_hierarchy_base(item)

    def _set_hierarchy_base(self, item: dict[str, Any]) -> None:
        level = (item.get("meta") or {}).get("hf__heading_level")
        if isinstance(level, int):
            self._hierarchy_base_level = min(5, max(1, level))

    def _infer_lower_level(self, item: dict[str, Any]) -> int:
        text = str(item.get("text", "")).strip()
        numbered = re.match(r"^(\d+(?:\.\d+){1,4})[.)]?\s+\S", text)
        if numbered:
            return min(5, 2 + numbered.group(1).count("."))

        metadata = item.get("meta") or {}
        font_size = metadata.get("hf__heading_font_size")
        if isinstance(font_size, (int, float)):
            normalized_size = round(float(font_size), 3)
            if self.h2_font_floor is not None and normalized_size >= self.h2_font_floor:
                return 3
            resolved = self.lower_level_by_size.get(normalized_size)
            if resolved is not None:
                return resolved

        hierarchy_level = metadata.get("hf__heading_level")
        if isinstance(hierarchy_level, int):
            if self._hierarchy_base_level is not None:
                return min(
                    5,
                    max(2, hierarchy_level - self._hierarchy_base_level + 1),
                )
            return min(5, max(3, hierarchy_level))
        level = item.get("level")
        if isinstance(level, int):
            return min(5, max(3, level))
        return 3

    def _discover_layout_chapters(
        self,
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> bool:
        """Resolve illustrated chapter spreads from reusable layout evidence.

        These VLRC reports share a design, not document-specific wording: a
        right-hand ``CONTENTS`` panel on the opener and a large H1 beside a
        running ``Chapter N`` marker on the first body page.  Using both pages
        avoids trusting decorative background text, which is often badly
        fragmented or repeated by PDF extraction.
        """
        positions = {
            reference: index for index, reference in enumerate(ordered_references)
        }
        page_references: dict[int, list[str]] = {}
        for reference in ordered_references:
            item = all_items.get(reference)
            if not item:
                continue
            page = self._item_page(item, all_items)
            if page is not None:
                page_references.setdefault(page, []).append(reference)

        records: list[dict[str, Any]] = []
        seen_numbers: set[str] = set()
        for contents_reference in ordered_references:
            contents_item = all_items.get(contents_reference)
            if not contents_item or not self._is_contents_label(
                str(contents_item.get("text", ""))
            ):
                continue
            contents_page = self._item_page(contents_item, all_items)
            if contents_page is None or not self._is_right_contents_panel(
                contents_item,
                contents_page,
            ):
                continue

            panel_references = self._contents_panel_references(
                contents_reference,
                contents_page,
                all_items,
                page_references.get(contents_page, []),
            )
            panel_items = [
                (reference, all_items[reference])
                for reference in panel_references
                if reference in all_items
            ]
            panel_text = " ".join(
                re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
                for reference, item in panel_items
                if reference != contents_reference
            )

            # A part divider also has a right-hand contents panel, but its
            # entries point to whole chapters.  It is not itself a chapter.
            if re.search(
                r"(?:^|\s)(?:\d+\s+)?chapter\s+"
                r"(?:\d+|[ivxlcdm]+)\b",
                panel_text,
                re.IGNORECASE,
            ):
                self.chapter_contents_refs.update(panel_references)
                continue

            opener_number = self._opener_chapter_number(
                contents_page,
                all_items,
                page_references.get(contents_page, []),
            )
            body_identity = self._first_body_chapter_identity(
                contents_page,
                opener_number,
                all_items,
                page_references,
            )
            if body_identity is None:
                continue
            chapter_number, h1_reference, h1_item = body_identity
            if chapter_number in seen_numbers:
                continue

            h1_text = re.sub(
                r"\s+", " ", str(h1_item.get("text", ""))
            ).strip()
            chapter_key = self._chapter_key(h1_text)
            if not chapter_key:
                continue

            opener_reference = self._chapter_opener_reference(
                contents_page,
                chapter_number,
                all_items,
                page_references.get(contents_page, []),
            )
            if opener_reference is None:
                # The chapter title can be graphical and absent from Docling.
                # Reuse the structurally reliable contents label as the anchor;
                # its visible output is replaced with the reconstructed title.
                opener_reference = contents_reference

            self.chapter_title_refs.add(opener_reference)
            self.chapter_h1_refs.add(h1_reference)
            self.chapter_key_by_ref[opener_reference] = chapter_key
            self.chapter_key_by_ref[h1_reference] = chapter_key
            self.chapter_title_text_by_ref[opener_reference] = (
                f"Chapter {chapter_number}: {h1_text}"
            )

            # A chapter-opening spread contains decorative title fragments,
            # source notes, and the visual outline.  The chapter anchor is the
            # only semantic content that should survive into accessible output.
            for reference in page_references.get(contents_page, []):
                if reference != opener_reference:
                    self.chapter_contents_refs.add(reference)

            headings, _ = self._chapter_contents_entries(panel_items)
            outline = {
                self._chapter_key(heading)
                for heading in headings
                if self._chapter_key(heading)
            }
            records.append(
                {
                    "number": chapter_number,
                    "key": chapter_key,
                    "page": contents_page,
                    "index": positions.get(contents_reference, 0),
                    "opener_ref": opener_reference,
                    "h1_ref": h1_reference,
                    "panel_text": panel_text,
                    "outline": outline,
                }
            )
            seen_numbers.add(chapter_number)

        if not records:
            return False

        records.sort(key=lambda record: (record["page"], record["index"]))
        self._discover_layout_back_matter(
            records,
            all_items,
            ordered_references,
            positions,
        )
        records.sort(key=lambda record: (record["page"], record["index"]))

        for index, record in enumerate(records):
            end_page = (
                records[index + 1]["page"] - 1
                if index + 1 < len(records)
                else max(page_references, default=record["page"])
            )
            chapter_number = record.get("number")
            chapter_key = str(record["key"])
            h1_reference = str(record.get("h1_ref", ""))

            body_items: list[tuple[str, dict[str, Any]]] = []
            body_headers: list[tuple[str, dict[str, Any]]] = []
            for page in range(int(record["page"]) + 1, end_page + 1):
                for reference in page_references.get(page, []):
                    item = all_items.get(reference)
                    if not item:
                        continue
                    body_items.append((reference, item))
                    text = re.sub(
                        r"\s+", " ", str(item.get("text", ""))
                    ).strip()
                    if chapter_number and self._is_running_chapter_marker(
                        text,
                        str(chapter_number),
                    ):
                        self.chapter_context_refs.add(reference)
                        continue
                    if _effective_raw_label(item) == "section_header":
                        body_headers.append((reference, item))

            if chapter_key == "appendices":
                appendix_groups: dict[
                    str, list[tuple[str, dict[str, Any]]]
                ] = {}
                for reference, item in body_headers:
                    self.forced_heading_levels[reference] = 3
                for reference, item in body_items:
                    if _effective_raw_label(item) not in {
                        "section_header",
                        "text",
                        "title",
                    }:
                        continue
                    text = re.sub(
                        r"\s+", " ", str(item.get("text", ""))
                    ).strip()
                    match = re.search(
                        r"\bappendix\s+([a-z0-9ivxlcdm]+)\b",
                        text,
                        re.IGNORECASE,
                    )
                    if match:
                        appendix_groups.setdefault(
                            match.group(1).casefold(), []
                        ).append((reference, item))
                for duplicates in appendix_groups.values():
                    first_reference, first_item = next(
                        (
                            (reference, item)
                            for reference, item in duplicates
                            if _effective_raw_label(item) == "section_header"
                            and not (item.get("meta") or {}).get(
                                "konverter_exclude_from_output"
                            )
                        ),
                        duplicates[0],
                    )
                    title_options = [
                        re.sub(
                            r"\s+", " ", str(item.get("text", ""))
                        ).strip()
                        for _, item in duplicates
                    ]
                    for _, duplicate_item in duplicates:
                        continuation = self._appendix_title_continuation(
                            duplicate_item,
                            body_items,
                        )
                        if continuation:
                            duplicate_text = re.sub(
                                r"\s+",
                                " ",
                                str(duplicate_item.get("text", "")),
                            ).strip()
                            title_options.append(
                                f"{duplicate_text} {continuation[1]}"
                            )
                            self.chapter_context_refs.add(continuation[0])
                    richest_text = self._canonical_appendix_title(
                        max(title_options, key=len)
                    )
                    self.forced_heading_levels[first_reference] = 2
                    self.chapter_title_text_by_ref[first_reference] = richest_text
                    record["outline"].add(
                        self._chapter_key(str(first_item.get("text", "")))
                    )
                    self.chapter_context_refs.update(
                        reference
                        for reference, _ in duplicates
                        if reference != first_reference
                    )

            panel_match_text = self._outline_match_key(
                str(record.get("panel_text", ""))
            )
            for reference, item in body_headers:
                if reference == h1_reference:
                    continue
                text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
                key = self._chapter_key(text)
                if not key:
                    continue
                if key == chapter_key:
                    if not h1_reference:
                        self.chapter_h1_refs.add(reference)
                        self.chapter_key_by_ref[reference] = chapter_key
                        h1_reference = reference
                    else:
                        self.chapter_context_refs.add(reference)
                    continue
                match_key = self._outline_match_key(text)
                if (
                    match_key
                    and re.search(
                        rf"(?<!\w){re.escape(match_key)}(?!\w)",
                        panel_match_text,
                    )
                ):
                    record["outline"].add(key)

            self.chapter_outlines[chapter_key] = set(record["outline"])

        self._layout_chapters_resolved = True
        return True

    def _discover_layout_back_matter(
        self,
        records: list[dict[str, Any]],
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
        positions: dict[str, int],
    ) -> None:
        """Add real back-matter openers without matching TOC entries."""
        last_numbered_page = max(int(record["page"]) for record in records)
        candidates: dict[str, list[tuple[int, int, str, dict[str, Any]]]] = {}
        for reference in ordered_references:
            item = all_items.get(reference)
            if not item or _effective_raw_label(item) != "section_header":
                continue
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            normalized = text.strip(" .").casefold()
            if normalized == "appendix":
                normalized = "appendices"
            if normalized not in {"appendices", "glossary", "bibliography"}:
                continue
            page = self._item_page(item, all_items)
            if page is None or page <= last_numbered_page:
                continue
            box = self._item_bbox(item)
            page_size = self.page_sizes.get(page)
            if box is None or page_size is None:
                continue
            _, top, _, bottom = box
            height = page_size[1]
            if max(top, bottom) < height * 0.64:
                continue
            candidates.setdefault(normalized, []).append(
                (page, positions.get(reference, 0), reference, item)
            )

        canonical = {
            "appendices": "Appendices",
            "glossary": "Glossary",
            "bibliography": "Bibliography",
        }
        for key in ("appendices", "glossary", "bibliography"):
            if not candidates.get(key):
                continue
            page, position, reference, item = min(candidates[key])
            self.chapter_title_refs.add(reference)
            self.chapter_key_by_ref[reference] = key
            self.chapter_title_text_by_ref[reference] = canonical[key]
            panel_text = ""
            outline: set[str] = set()
            same_page_references = [
                candidate_reference
                for candidate_reference in ordered_references
                if self._item_page(
                    all_items.get(candidate_reference, {}), all_items
                )
                == page
            ]
            contents_reference = next(
                (
                    candidate_reference
                    for candidate_reference in same_page_references
                    if self._is_contents_label(
                        str(
                            all_items.get(candidate_reference, {}).get("text", "")
                        )
                    )
                    and self._is_right_contents_panel(
                        all_items.get(candidate_reference, {}), page
                    )
                ),
                None,
            )
            if contents_reference is not None:
                panel_references = self._contents_panel_references(
                    contents_reference,
                    page,
                    all_items,
                    same_page_references,
                )
                panel_items = [
                    (candidate_reference, all_items[candidate_reference])
                    for candidate_reference in panel_references
                    if candidate_reference in all_items
                ]
                panel_text = " ".join(
                    re.sub(
                        r"\s+", " ", str(candidate.get("text", ""))
                    ).strip()
                    for candidate_reference, candidate in panel_items
                    if candidate_reference != contents_reference
                )
                headings, _ = self._chapter_contents_entries(panel_items)
                outline = {
                    self._chapter_key(heading)
                    for heading in headings
                    if self._chapter_key(heading)
                }
                for candidate_reference in same_page_references:
                    if candidate_reference != reference:
                        self.chapter_contents_refs.add(candidate_reference)
            records.append(
                {
                    "number": None,
                    "key": key,
                    "page": page,
                    "index": position,
                    "opener_ref": reference,
                    "h1_ref": "",
                    "panel_text": panel_text,
                    "outline": outline,
                }
            )

    def _is_right_contents_panel(
        self,
        item: dict[str, Any],
        page: int,
    ) -> bool:
        box = self._item_bbox(item)
        page_size = self.page_sizes.get(page)
        if box is None or page_size is None:
            return False
        left, top, right, bottom = box
        width, height = page_size
        return bool(
            0 <= left <= right <= width * 1.03
            and 0 <= min(top, bottom)
            and max(top, bottom) <= height * 1.03
            and left >= width * 0.62
        )

    def _contents_panel_references(
        self,
        contents_reference: str,
        page: int,
        all_items: dict[str, dict[str, Any]],
        page_references: list[str],
    ) -> list[str]:
        contents_box = self._item_bbox(all_items[contents_reference])
        if contents_box is None:
            return [contents_reference]
        left, top, _, _ = contents_box
        output = [contents_reference]
        for reference in page_references:
            if reference == contents_reference:
                continue
            item = all_items.get(reference)
            box = self._item_bbox(item or {})
            if box is None:
                continue
            item_left, item_top, _, _ = box
            if item_left >= left - 24 and item_top <= top + 8:
                output.append(reference)
        return output

    def _opener_chapter_number(
        self,
        page: int,
        all_items: dict[str, dict[str, Any]],
        page_references: list[str],
    ) -> str | None:
        for reference in page_references:
            item = all_items.get(reference)
            if not item:
                continue
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            parsed = self._parse_chapter_title(text)
            if parsed is not None:
                return parsed[0].casefold()
        return None

    def _first_body_chapter_identity(
        self,
        opener_page: int,
        opener_number: str | None,
        all_items: dict[str, dict[str, Any]],
        page_references: dict[int, list[str]],
    ) -> tuple[str, str, dict[str, Any]] | None:
        for page in range(opener_page + 1, opener_page + 4):
            references = page_references.get(page, [])
            marker_numbers = [
                number
                for reference in references
                if (
                    number := self._running_chapter_number(
                        str((all_items.get(reference) or {}).get("text", ""))
                    )
                )
            ]
            chapter_number = opener_number or (marker_numbers[0] if marker_numbers else None)
            if chapter_number is None:
                continue
            candidates: list[tuple[float, int, str, dict[str, Any]]] = []
            width, height = self.page_sizes.get(page, (0.0, 0.0))
            for order, reference in enumerate(references):
                item = all_items.get(reference)
                if not item or _effective_raw_label(item) != "section_header":
                    continue
                text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
                if (
                    not text
                    or len(text) > 180
                    or self._is_contents_label(text)
                    or self._is_running_chapter_marker(text, chapter_number)
                    or self._is_citation_like(text, item)
                ):
                    continue
                box = self._item_bbox(item)
                if box is None:
                    continue
                left, top, right, bottom = box
                if width and (left < width * 0.22 or right > width * 1.03):
                    continue
                font_size = (item.get("meta") or {}).get("hf__heading_font_size")
                visual_size = (
                    float(font_size)
                    if isinstance(font_size, (int, float))
                    else abs(top - bottom)
                )
                if visual_size < 11:
                    continue
                score = visual_size * 10
                if height and max(top, bottom) >= height * 0.76:
                    score += 100
                score -= order * 0.01
                candidates.append((score, -order, reference, item))
            if candidates:
                _, _, reference, item = max(candidates)
                return chapter_number, reference, item
        return None

    def _chapter_opener_reference(
        self,
        page: int,
        chapter_number: str,
        all_items: dict[str, dict[str, Any]],
        page_references: list[str],
    ) -> str | None:
        candidates: list[tuple[float, str]] = []
        for reference in page_references:
            item = all_items.get(reference)
            if not item or _effective_raw_label(item) not in {"section_header", "title"}:
                continue
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            parsed = self._parse_chapter_title(text)
            if parsed is None or parsed[0].casefold() != chapter_number.casefold():
                continue
            box = self._item_bbox(item)
            font_size = (item.get("meta") or {}).get("hf__heading_font_size")
            score = float(font_size) if isinstance(font_size, (int, float)) else 0.0
            if box is not None:
                score += abs(box[1] - box[3])
            candidates.append((score, reference))
        return max(candidates, default=(0.0, ""))[1] or None

    @staticmethod
    def _running_chapter_number(value: str) -> str | None:
        text = re.sub(r"\s+", " ", value).strip(" .:–—-")
        if not text or len(text) > 80:
            return None
        match = re.match(
            r"^chapter\s+(\d+|[ivxlcdm]+)\b",
            text,
            re.IGNORECASE,
        )
        return match.group(1).casefold() if match else None

    @classmethod
    def _is_running_chapter_marker(cls, value: str, number: str) -> bool:
        text = re.sub(r"\s+", " ", value).strip(" .:–—-")
        detected = cls._running_chapter_number(text)
        if detected == number.casefold():
            return True
        return bool(
            len(text) <= 36
            and re.fullmatch(
                rf"(?:[a-z]{{0,4}}ter)\s+{re.escape(number)}"
                rf"(?:\s+{re.escape(number)})+",
                text,
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _outline_match_key(value: str) -> str:
        return re.sub(
            r"\s+",
            " ",
            re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE),
        ).strip()

    @staticmethod
    def _canonical_appendix_title(value: str) -> str:
        text = re.sub(r"\s+", " ", value).strip(" .:–—-")
        match = re.search(
            r"\bappendix\s+([a-z0-9ivxlcdm]+)\b",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return text
        identifier = match.group(1).upper() if match.group(1).isalpha() else match.group(1)
        before = text[: match.start()].strip(" .:–—-")
        after = text[match.end() :].strip(" .:–—-")
        subtitle = " ".join(part for part in (before, after) if part)
        return f"Appendix {identifier}: {subtitle}" if subtitle else f"Appendix {identifier}"

    @classmethod
    def _appendix_title_continuation(
        cls,
        title_item: dict[str, Any],
        body_items: list[tuple[str, dict[str, Any]]],
    ) -> tuple[str, str] | None:
        title_text = re.sub(
            r"\s+", " ", str(title_item.get("text", ""))
        ).strip()
        match = re.fullmatch(
            r"appendix\s+[a-z0-9ivxlcdm]+",
            title_text,
            re.IGNORECASE,
        )
        title_box = cls._item_bbox(title_item)
        if (
            match is None
            or title_box is None
            or _effective_raw_label(title_item) != "text"
        ):
            return None
        title_page = _first_page(title_item)
        title_left, _, _, title_bottom = title_box
        candidates: list[tuple[float, str, str]] = []
        for reference, item in body_items:
            if item is title_item or _first_page(item) != title_page:
                continue
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            if (
                not text
                or len(text) > 100
                or len(text.split()) > 12
                or re.search(r"[.!?;:]$", text)
                or re.search(r"\bappendix\s+", text, re.IGNORECASE)
            ):
                continue
            box = cls._item_bbox(item)
            if box is None:
                continue
            left, top, _, _ = box
            vertical_gap = title_bottom - top
            if abs(left - title_left) <= 36 and -4 <= vertical_gap <= 45:
                candidates.append((abs(vertical_gap), reference, text))
        if not candidates:
            return None
        _, reference, text = min(candidates)
        return reference, text

    def _discover_chapter_outlines(
        self,
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> None:
        # Layout-aware reconstruction is the primary path for illustrated legal
        # reports.  It is anchored by the physical chapter-contents panel and
        # the first body-page heading, not by a document name or hard-coded
        # chapter title.  The older signal-only fallback below remains useful
        # for synthetic inputs and PDFs without page geometry.
        if self.page_sizes and self._discover_layout_chapters(
            all_items,
            ordered_references,
        ):
            return

        chapter_starts: list[tuple[int, str, str, int]] = []
        chapter_pages_by_number: dict[str, tuple[str, int]] = {}
        chapter_h1_numbers: set[str] = set()

        # Prefer an explicit chapter-opening CONTENTS panel. Older untagged
        # InDesign PDFs often merge the chapter number, a decorative duplicate
        # number and the subtitle into one Docling item (for example,
        # ``Chapter 2 2 Section Name``). The contents label is a much stronger
        # boundary signal than the hierarchy level assigned to that item.
        for contents_index, contents_reference in enumerate(ordered_references):
            contents_item = all_items.get(contents_reference)
            if not contents_item or not self._is_contents_label(
                str(contents_item.get("text", ""))
            ):
                continue
            contents_page = self._item_page(contents_item, all_items)
            if contents_page is None:
                continue
            opener: tuple[int, str, str, str] | None = None
            for candidate_index in range(contents_index - 1, -1, -1):
                candidate_reference = ordered_references[candidate_index]
                candidate = all_items.get(candidate_reference)
                if not candidate:
                    continue
                candidate_page = self._item_page(candidate, all_items)
                if candidate_page != contents_page:
                    if candidate_page is not None and candidate_page < contents_page:
                        break
                    continue
                parsed = self._parse_chapter_title(str(candidate.get("text", "")))
                if parsed is None:
                    continue
                chapter_number, subtitle = parsed
                if not subtitle:
                    continue
                opener = (
                    candidate_index,
                    candidate_reference,
                    chapter_number,
                    subtitle,
                )
                break
            if opener is None:
                continue
            opener_index, opener_reference, chapter_number, subtitle = opener
            chapter_key = self._chapter_key(subtitle)
            if not chapter_key:
                continue
            self.chapter_title_refs.add(opener_reference)
            self.chapter_key_by_ref[opener_reference] = chapter_key
            self.chapter_title_text_by_ref[opener_reference] = (
                f"Chapter {chapter_number}: {subtitle}"
            )
            self.chapter_contents_refs.add(contents_reference)
            chapter_pages_by_number[chapter_number.casefold()] = (
                chapter_key,
                contents_page,
            )
            chapter_starts.append(
                (opener_index, opener_reference, chapter_key, contents_page)
            )

        # Illustrated reports often split the chapter opener into ``Chapter N``
        # and a subtitle, then repeat the same pair as the running heading on the
        # first body page.  Docling can label any of those fragments as text,
        # title, or section_header.  Pair them from text + page order first so the
        # opener becomes the chapter title and the repeated subtitle becomes H1.
        for index, reference in enumerate(ordered_references):
            marker_item = all_items.get(reference)
            if not marker_item or reference == self.main_title_ref:
                continue
            marker_text = str(marker_item.get("text", "")).strip()
            chapter_number = self._chapter_number(marker_text)
            marker_page = self._item_page(marker_item, all_items)
            if chapter_number is None or marker_page is None:
                continue
            subtitle_match = self._find_split_chapter_subtitle(
                index,
                marker_page,
                all_items,
                ordered_references,
            )
            if subtitle_match is None:
                continue
            subtitle_index, subtitle_reference, subtitle_item = subtitle_match
            chapter_key = self._chapter_key(str(subtitle_item.get("text", "")))
            if not chapter_key:
                continue

            previous = chapter_pages_by_number.get(chapter_number)
            if previous is None:
                chapter_pages_by_number[chapter_number] = (chapter_key, marker_page)
                self.chapter_title_refs.add(reference)
                self.chapter_title_continuation_refs.add(subtitle_reference)
                self.chapter_key_by_ref[reference] = chapter_key
                self.chapter_key_by_ref[subtitle_reference] = chapter_key
                chapter_starts.append(
                    (subtitle_index, reference, chapter_key, marker_page)
                )
            elif previous[0] == chapter_key and marker_page > previous[1]:
                self.chapter_context_refs.add(reference)
                if chapter_number not in chapter_h1_numbers:
                    self.chapter_h1_refs.add(subtitle_reference)
                    self.chapter_key_by_ref[subtitle_reference] = chapter_key
                    chapter_h1_numbers.add(chapter_number)
                else:
                    self.chapter_context_refs.add(subtitle_reference)

        discovered_keys = {
            chapter_key for _, _, chapter_key, _ in chapter_starts
        }
        for index, reference in enumerate(ordered_references):
            title_item = all_items.get(reference)
            if not title_item or reference == self.main_title_ref:
                continue
            if reference in (
                self.chapter_title_refs
                | self.chapter_title_continuation_refs
                | self.chapter_context_refs
                | self.chapter_h1_refs
            ):
                continue

            raw_label = _effective_raw_label(title_item)
            title = str(title_item.get("text", "")).strip()
            title_page = self._item_page(title_item, all_items)
            if title_page is None:
                continue
            parsed_title = self._parse_chapter_title(title)
            if parsed_title is not None:
                known_chapter = chapter_pages_by_number.get(
                    parsed_title[0].casefold()
                )
                if known_chapter is not None and title_page > known_chapter[1]:
                    self.chapter_context_refs.add(reference)
                    continue
            chapter_key = self._chapter_key(title)
            if not chapter_key:
                continue

            is_explicit_title = raw_label == "title"
            is_inferred_title = raw_label == "section_header" and (
                self._is_named_back_matter_chapter(title)
                or self._has_matching_chapter_heading(
                    chapter_key,
                    title_page,
                    index,
                    all_items,
                    ordered_references,
                )
            )
            if not is_explicit_title and not is_inferred_title:
                continue

            if chapter_key in discovered_keys:
                if title_page > next(
                    page
                    for _, _, key, page in chapter_starts
                    if key == chapter_key
                ):
                    self.chapter_h1_refs.add(reference)
                    self.chapter_key_by_ref[reference] = chapter_key
                continue

            self.chapter_title_refs.add(reference)
            self.chapter_key_by_ref[reference] = chapter_key
            chapter_starts.append((index, reference, chapter_key, title_page))
            discovered_keys.add(chapter_key)

        chapter_starts.sort(key=lambda value: value[0])

        for index, _, chapter_key, title_page in chapter_starts:
            candidates: list[tuple[str, dict[str, Any]]] = []
            container_children: dict[str, set[str]] = {}
            for candidate_reference in ordered_references[index + 1 :]:
                candidate = all_items.get(candidate_reference)
                if not candidate:
                    continue
                if candidate_reference in self.chapter_title_refs:
                    break
                candidate_page = self._item_page(candidate, all_items)
                if candidate_page is not None and candidate_page > title_page:
                    break
                if candidate_page != title_page:
                    continue

                raw_label = _effective_raw_label(candidate)
                if raw_label in {"list", "form_area", "key_value_area", "group"}:
                    child_refs = [
                        str(child.get("$ref", ""))
                        for child in candidate.get("children", [])
                        if str(child.get("$ref", ""))
                    ]
                    container_children[candidate_reference] = set(child_refs)
                    candidates.extend(
                        (child_reference, child_item)
                        for child_reference in child_refs
                        if (child_item := all_items.get(child_reference)) is not None
                    )
                elif raw_label in {"list_item", "text", "section_header"}:
                    candidates.append((candidate_reference, candidate))

            headings, consumed_refs = self._chapter_contents_entries(candidates)
            outline = {
                self._chapter_key(heading)
                for heading in headings
                if self._chapter_key(heading)
            }
            self.chapter_contents_refs.update(consumed_refs)
            for container_reference, child_refs in container_children.items():
                if child_refs & consumed_refs:
                    self.chapter_contents_refs.add(container_reference)
            self.chapter_outlines[chapter_key] = outline

        # The first body page repeats the chapter identity and is the chapter's
        # H1. Later repetitions are running page furniture. Resolve this from
        # stable Docling text order rather than the rewritten hierarchy tree.
        for position, (start_index, start_reference, chapter_key, title_page) in enumerate(
            chapter_starts
        ):
            parsed_title = self._parse_chapter_title(
                str((all_items.get(start_reference) or {}).get("text", ""))
            )
            chapter_number = parsed_title[0].casefold() if parsed_title else None
            end_index = (
                chapter_starts[position + 1][0]
                if position + 1 < len(chapter_starts)
                else len(ordered_references)
            )
            found_h1 = False
            for reference in ordered_references[start_index + 1 : end_index]:
                item = all_items.get(reference)
                if not item:
                    continue
                page = self._item_page(item, all_items)
                if page is None or page <= title_page:
                    continue
                text = str(item.get("text", "")).strip()
                parsed_running = self._parse_chapter_title(text)
                if (
                    chapter_number is not None
                    and parsed_running is not None
                    and parsed_running[0].casefold() == chapter_number
                ):
                    self.chapter_context_refs.add(reference)
                    continue
                if self._chapter_key(text) != chapter_key:
                    continue
                if not self._can_promote_outline_item(item):
                    continue
                if not found_h1:
                    self.chapter_h1_refs.add(reference)
                    self.chapter_key_by_ref[reference] = chapter_key
                    found_h1 = True
                else:
                    self.chapter_context_refs.add(reference)

    def _has_matching_chapter_heading(
        self,
        chapter_key: str,
        title_page: int,
        start_index: int,
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> bool:
        for reference in ordered_references[start_index + 1 :]:
            item = all_items.get(reference)
            if not item:
                continue
            page = self._item_page(item, all_items)
            if page is not None and page > title_page + 2:
                return False
            if _effective_raw_label(item) == "section_header":
                text = str(item.get("text", ""))
                if self._is_numbered_chapter(text) or re.match(
                    r"^\d+\.\s+\S",
                    text.strip(),
                ):
                    return self._chapter_key(text) == chapter_key
        return False

    @classmethod
    def _find_split_chapter_subtitle(
        cls,
        marker_index: int,
        marker_page: int,
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> tuple[int, str, dict[str, Any]] | None:
        marker_item = all_items.get(ordered_references[marker_index], {})
        marker_box = cls._item_bbox(marker_item)
        positioned: list[
            tuple[float, float, int, str, dict[str, Any]]
        ] = []
        fallback: tuple[int, str, dict[str, Any]] | None = None

        for candidate_index, reference in enumerate(ordered_references):
            if candidate_index == marker_index:
                continue
            item = all_items.get(reference)
            if not item:
                continue
            page = cls._item_page(item, all_items)
            if page != marker_page:
                continue
            raw_label = _effective_raw_label(item)
            text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
            if raw_label in {"page_header", "page_footer", "picture", "table"}:
                continue
            if cls._is_contents_label(text) or cls._is_page_marker(text):
                continue
            if cls._chapter_number(text) is not None:
                continue
            if not cls._is_likely_chapter_subtitle(text):
                continue

            candidate_box = cls._item_bbox(item)
            if marker_box is not None and candidate_box is not None:
                marker_mid = (marker_box[1] + marker_box[3]) / 2
                candidate_mid = (candidate_box[1] + candidate_box[3]) / 2
                vertical_distance = abs(candidate_mid - marker_mid)
                candidate_height = abs(candidate_box[3] - candidate_box[1])
                positioned.append(
                    (
                        vertical_distance,
                        -candidate_height,
                        candidate_index,
                        reference,
                        item,
                    )
                )
            elif (
                fallback is None
                and marker_index < candidate_index <= marker_index + 10
            ):
                fallback = candidate_index, reference, item

        if positioned:
            vertical_distance, _, candidate_index, reference, item = min(positioned)
            marker_height = abs(marker_box[3] - marker_box[1]) if marker_box else 0
            if vertical_distance <= max(90.0, marker_height * 5):
                return candidate_index, reference, item
        return fallback

    @staticmethod
    def _item_bbox(item: dict[str, Any]) -> tuple[float, float, float, float] | None:
        provenance = item.get("prov") or []
        bbox = provenance[0].get("bbox") if provenance else None
        if not bbox:
            return None
        try:
            return (
                float(bbox.get("l", 0)),
                float(bbox.get("t", 0)),
                float(bbox.get("r", 0)),
                float(bbox.get("b", 0)),
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def _chapter_contents_entries(
        cls,
        candidates: list[tuple[str, dict[str, Any]]],
    ) -> tuple[list[str], set[str]]:
        headings: list[str] = []
        consumed_refs: set[str] = set()
        pending_page_ref: str | None = None
        previous_was_numbered = False
        seen_refs: set[str] = set()

        for reference, item in candidates:
            if reference in seen_refs:
                continue
            seen_refs.add(reference)
            raw_label = _effective_raw_label(item)
            raw_text = str(item.get("text", ""))
            if not raw_text.strip() or raw_label not in {
                "list_item",
                "text",
                "section_header",
            }:
                pending_page_ref = None
                previous_was_numbered = False
                continue

            lines = [
                re.sub(r"\s+", " ", line).strip()
                for line in raw_text.splitlines()
                if line.strip()
            ] or [re.sub(r"\s+", " ", raw_text).strip()]
            for text in lines:
                if cls._is_contents_label(text):
                    consumed_refs.add(reference)
                    pending_page_ref = None
                    previous_was_numbered = False
                    continue

                heading = cls._chapter_contents_heading(text)
                if heading:
                    headings.append(heading)
                    consumed_refs.add(reference)
                    if pending_page_ref is not None:
                        consumed_refs.add(pending_page_ref)
                        pending_page_ref = None
                    previous_was_numbered = True
                    continue

                if cls._is_page_marker(text):
                    pending_page_ref = reference
                    previous_was_numbered = False
                    continue

                if pending_page_ref is not None and len(text) <= 250:
                    headings.append(text.strip(" .–—-"))
                    consumed_refs.update({pending_page_ref, reference})
                    pending_page_ref = None
                    previous_was_numbered = True
                    continue

                if (
                    previous_was_numbered
                    and headings
                    and cls._is_outline_continuation(text)
                ):
                    headings[-1] = f"{headings[-1]} {text.strip(' .–—-')}"
                    consumed_refs.add(reference)
                    continue

                pending_page_ref = None
                previous_was_numbered = False

        return headings, consumed_refs

    @staticmethod
    def _can_promote_outline_item(item: dict[str, Any]) -> bool:
        raw = _effective_raw_label(item)
        text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
        return (
            raw in {"section_header", "text", "title", "list_item"}
            and 0 < len(text) <= 250
            and len(text.split()) <= 24
        )

    @staticmethod
    def _is_outline_continuation(value: str) -> bool:
        text = re.sub(r"\s+", " ", value).strip()
        return bool(
            text
            and len(text) <= 120
            and len(text.split()) <= 14
            and not re.search(r"[.!?;:]$", text)
            and not HeadingResolver._is_contents_label(text)
            and not HeadingResolver._is_page_marker(text)
            and HeadingResolver._chapter_number(text) is None
        )

    @staticmethod
    def _is_citation_like(value: str, item: dict[str, Any]) -> bool:
        text = re.sub(r"\s+", " ", value).strip()
        font_size = (item.get("meta") or {}).get("hf__heading_font_size")
        return bool(
            isinstance(font_size, (int, float))
            and float(font_size) <= 6.5
            and re.match(r"^\d{1,4}\s+", text)
            and re.search(
                r"(?:\bibid\b|\bsubmissions?\b|\bconsultations?\b|"
                r"\broundtables?\b|\babove\s+n\b|\bact\s+\d{4}\b|"
                r"\bss?\s+\d|\[[12]\d{3}\])",
                text,
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _is_contents_label(value: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:chapter\s+)?contents|table\s+of\s+contents",
                value.strip(),
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _is_likely_chapter_subtitle(value: str) -> bool:
        text = re.sub(r"\s+", " ", value).strip()
        return bool(
            text
            and len(text) <= 160
            and 1 <= len(text.split()) <= 16
            and not re.search(r"[.!?;:]$", text)
            and not re.match(r"^(?:https?://|www\.)", text, re.IGNORECASE)
            and not HeadingResolver._chapter_contents_heading(text)
        )

    @staticmethod
    def _chapter_number(value: str) -> str | None:
        match = re.fullmatch(
            r"chapter\s+(\d+|[ivxlcdm]+)[.:)]?",
            value.strip(),
            re.IGNORECASE,
        )
        return match.group(1).casefold() if match else None

    def _build_lower_style_levels(self, all_items: dict[str, dict[str, Any]]) -> None:
        chapter_keys = set(self.chapter_outlines)
        outline_keys = {
            heading
            for headings in self.chapter_outlines.values()
            for heading in headings
        }
        h2_sizes = [
            round(float(font_size), 3)
            for item in all_items.values()
            if (
                _effective_raw_label(item) == "section_header"
                and self._chapter_key(str(item.get("text", ""))) in outline_keys
                and isinstance(
                    font_size := (item.get("meta") or {}).get("hf__heading_font_size"),
                    (int, float),
                )
            )
        ]
        self.h2_font_floor = min(h2_sizes) if h2_sizes else None
        sizes: set[float] = set()
        for item in all_items.values():
            if _effective_raw_label(item) != "section_header":
                continue
            key = self._chapter_key(str(item.get("text", "")))
            if key in chapter_keys or key in outline_keys:
                continue
            font_size = (item.get("meta") or {}).get("hf__heading_font_size")
            if isinstance(font_size, (int, float)):
                normalized_size = round(float(font_size), 3)
                if self.h2_font_floor is None or normalized_size < self.h2_font_floor:
                    sizes.add(normalized_size)

        for index, font_size in enumerate(sorted(sizes, reverse=True)):
            self.lower_level_by_size[font_size] = min(5, 3 + index)

    @staticmethod
    def _item_page(
        item: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
    ) -> int | None:
        provenance = item.get("prov") or []
        if provenance:
            return int(provenance[0].get("page_no", 1))
        for child in item.get("children", []):
            child_item = all_items.get(str(child.get("$ref", "")))
            if child_item and child_item.get("prov"):
                return _first_page(child_item)
        return None

    @staticmethod
    def _chapter_contents_heading(value: str) -> str | None:
        normalized = re.sub(r"\s+", " ", value).strip()
        match = re.match(
            r"^(?:p(?:age)?\.?\s*)?(?:\d+|[ivxlcdm]+)\s+(.+?)$",
            normalized,
            re.IGNORECASE,
        )
        if not match:
            return None
        heading = re.sub(r"\.{2,}\s*(?:\d+|[ivxlcdm]+)?$", "", match.group(1)).strip(
            " .–—-"
        )
        return heading if heading and len(heading) <= 250 else None

    @staticmethod
    def _is_page_marker(value: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:p(?:age)?\.?\s*)?(?:\d+|[ivxlcdm]+)",
                value.strip(),
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _chapter_key(value: str) -> str:
        parsed = HeadingResolver._parse_chapter_title(value)
        if parsed is not None and parsed[1]:
            value = parsed[1]
        without_number = re.sub(
            r"^(?:chapter\s+)?\d+[.:)]?\s*",
            "",
            value.strip(),
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", without_number).strip(" .–—-").casefold()

    @staticmethod
    def _is_numbered_chapter(value: str) -> bool:
        # Numbered recommendations and model sub-sections (``1. General
        # Description``) are headings, not chapters.  Only an explicit chapter
        # marker can start a numbered chapter.
        return HeadingResolver._parse_chapter_title(value) is not None

    @staticmethod
    def _parse_chapter_title(value: str) -> tuple[str, str] | None:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized or len(normalized) > 180:
            return None
        matches = list(
            re.finditer(
                r"chapter\s*(\d+|[ivxlcdm]+)\b",
                normalized,
                re.IGNORECASE,
            )
        )
        if not matches:
            return None
        match = matches[-1]
        # Accept normal ``Chapter N: Title`` openers and the occasional
        # title-first layout (``Other Issues Chapter 7``), but never a chapter
        # mention embedded in prose or repeated decorative OCR.
        if match.start() > 60 and match.end() < len(normalized) - 12:
            return None
        number = match.group(1)
        tail = normalized[match.end() :].strip(" .:–—-")
        tail = re.sub(
            rf"^(?:{re.escape(number)}\b\s*)+",
            "",
            tail,
            flags=re.IGNORECASE,
        ).strip(" .:–—-")
        tail = re.sub(
            rf"^apter\s+{re.escape(number)}\b"
            rf"(?:\s+{re.escape(number)}\b)*\s*",
            "",
            tail,
            flags=re.IGNORECASE,
        ).strip(" .:–—-")
        return number, tail

    @staticmethod
    def _is_named_back_matter_chapter(value: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:appendix|appendices|"
                r"bibliography|glossary|references|"
                r"acknowledg(?:e)?ments)",
                value.strip(),
                re.IGNORECASE,
            )
        )


@dataclass
class PipelineOutput:
    blocks: list[dict[str, Any]]
    review_items: list[dict[str, Any]]
    metadata_payload: dict[str, Any]
    raw_docling: dict[str, Any]
    doc_confidence: dict[str, Any]
    warnings: list[str]
    elapsed_seconds: float


class KonverterPipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._docling_converter: Any = None
        self._docling_lock = threading.Lock()

    def process(self, pdf_path: Path, stage: StageCallback) -> PipelineOutput:
        started = time.monotonic()
        stage(1, "Preparing document")
        raw_document, blocks, doc_confidence, warnings = self._run_docling(
            pdf_path, stage
        )

        stage(4, "Extracting metadata")
        try:
            metadata_payload = extract_metadata_from_docling(
                raw_document,
                pdf_path,
                self.settings,
            )
        except Exception as exc:
            warnings.append(f"Rule-based metadata extraction failed: {exc}")
            metadata_payload = empty_metadata_payload(self.settings)

        stage(5, "Scoring confidence")
        review_items = self._build_review_items(blocks)
        stage(6, "Preparing review")
        return PipelineOutput(
            blocks=blocks,
            review_items=review_items,
            metadata_payload=metadata_payload,
            raw_docling=raw_document,
            doc_confidence=doc_confidence,
            warnings=warnings,
            elapsed_seconds=time.monotonic() - started,
        )

    def _run_docling(
        self,
        pdf_path: Path,
        stage: StageCallback,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[str]]:
        stage(2, "Extracting content")
        converter = self._get_docling_converter()
        with self._docling_lock:
            result = converter.convert(pdf_path)
        stage(3, "Detecting document structure")
        hierarchy = apply_hierarchy(
            result,
            pdf_path,
            package_only=not self.settings.rule_based_headings,
        )
        raw_document = result.document.export_to_dict()
        attach_hierarchy_metadata(raw_document, hierarchy)
        warnings = list(hierarchy.warnings)
        warnings.extend(annotate_pdf_artifacts(raw_document, pdf_path))
        callout_regions, callout_warnings = detect_callout_regions(pdf_path)
        warnings.extend(callout_warnings)
        cluster_confidences = self._cluster_confidences(result)
        confidence_by_ref = self._confidence_by_reference(
            raw_document, cluster_confidences
        )
        blocks = self._blocks_from_document(raw_document, confidence_by_ref)
        blocks = group_visual_callouts(blocks, callout_regions)
        confidence = getattr(result, "confidence", None)
        doc_confidence = {
            "layout_score": getattr(confidence, "layout_score", None),
            "mean_score": getattr(confidence, "mean_score", None),
            "mean_grade": str(getattr(confidence, "mean_grade", "")) or None,
            "ocr_score": getattr(confidence, "ocr_score", None),
            "table_score": getattr(confidence, "table_score", None),
            "parse_score": getattr(confidence, "parse_score", None),
        }
        return raw_document, blocks, doc_confidence, warnings

    def _get_docling_converter(self) -> Any:
        if self._docling_converter is not None:
            return self._docling_converter
        with self._docling_lock:
            if self._docling_converter is not None:
                return self._docling_converter
            try:
                from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
                from docling.datamodel.accelerator_options import (
                    AcceleratorDevice,
                    AcceleratorOptions,
                )
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import (
                    PdfPipelineOptions,
                    TableStructureOptions,
                )
                from docling.document_converter import (
                    DocumentConverter,
                    PdfFormatOption,
                )
            except ImportError as exc:
                raise RuntimeError(
                    'Docling dependencies are missing. Install the backend with: pip install -e "./backend[docling]"'
                ) from exc

            options = PdfPipelineOptions()
            options.do_ocr = self.settings.do_ocr
            options.do_table_structure = self.settings.do_table_structure
            options.table_structure_options = TableStructureOptions(
                do_cell_matching=True
            )
            named_devices = {
                name: getattr(AcceleratorDevice, name.upper(), name)
                for name in ("auto", "cpu", "cuda", "mps", "xpu")
            }
            options.accelerator_options = AcceleratorOptions(
                device=named_devices.get(
                    self.settings.docling_device,
                    self.settings.docling_device,
                ),
            )
            self._docling_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=options,
                        backend=PyPdfiumDocumentBackend,
                    )
                }
            )
            return self._docling_converter

    @staticmethod
    def _cluster_confidences(result: Any) -> list[tuple[int, dict[str, float], float]]:
        clusters: list[tuple[int, dict[str, float], float]] = []
        for page in result.pages:
            layout = getattr(getattr(page, "predictions", None), "layout", None)
            for cluster in getattr(layout, "clusters", []) if layout else []:
                bbox = cluster.bbox
                clusters.append(
                    (
                        int(page.page_no),
                        {
                            "l": float(bbox.l),
                            "t": float(bbox.t),
                            "r": float(bbox.r),
                            "b": float(bbox.b),
                        },
                        float(cluster.confidence),
                    )
                )
        return clusters

    @classmethod
    def _confidence_by_reference(
        cls,
        document: dict[str, Any],
        clusters: list[tuple[int, dict[str, float], float]],
    ) -> dict[str, float | None]:
        pages = document.get("pages", {})
        clusters_by_page: dict[int, list[tuple[dict[str, float], float]]] = {}
        for page_no, bounds, confidence in clusters:
            clusters_by_page.setdefault(page_no, []).append((bounds, confidence))
        output: dict[str, float | None] = {}
        for collection in (
            "texts",
            "pictures",
            "tables",
            "form_items",
            "key_value_items",
        ):
            for item in document.get(collection, []):
                best_iou = 0.0
                best_confidence: float | None = None
                for provenance in item.get("prov", []):
                    page_no = int(provenance.get("page_no", 1))
                    bbox = provenance.get("bbox")
                    page_meta = pages.get(str(page_no), pages.get(page_no, {}))
                    height = float(page_meta.get("size", {}).get("height", 0))
                    if not bbox:
                        continue
                    normalised = cls._top_left_bbox(bbox, height)
                    for cluster_bbox, confidence in clusters_by_page.get(page_no, ()):
                        iou = cls._bbox_iou(normalised, cluster_bbox)
                        if iou > best_iou:
                            best_iou = iou
                            best_confidence = confidence
                output[str(item.get("self_ref", ""))] = (
                    best_confidence if best_iou > 0.3 else None
                )
        return output

    @staticmethod
    def _top_left_bbox(bbox: dict[str, Any], page_height: float) -> dict[str, float]:
        left = float(bbox.get("l", 0))
        right = float(bbox.get("r", 0))
        top = float(bbox.get("t", 0))
        bottom = float(bbox.get("b", 0))
        if (
            str(bbox.get("coord_origin", "")).upper().endswith("BOTTOMLEFT")
            and page_height > 0
        ):
            top, bottom = page_height - top, page_height - bottom
        return {
            "l": min(left, right),
            "t": min(top, bottom),
            "r": max(left, right),
            "b": max(top, bottom),
        }

    @staticmethod
    def _bbox_iou(first: dict[str, float], second: dict[str, float]) -> float:
        left = max(first["l"], second["l"])
        top = max(first["t"], second["t"])
        right = min(first["r"], second["r"])
        bottom = min(first["b"], second["b"])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        first_area = max(0.0, first["r"] - first["l"]) * max(
            0.0, first["b"] - first["t"]
        )
        second_area = max(0.0, second["r"] - second["l"]) * max(
            0.0, second["b"] - second["t"]
        )
        union = first_area + second_area - intersection
        return intersection / union if union else 0.0

    def _blocks_from_document(
        self,
        document: dict[str, Any],
        confidence_by_ref: dict[str, float | None],
    ) -> list[dict[str, Any]]:
        all_items: dict[str, dict[str, Any]] = {}
        for collection in (
            "texts",
            "pictures",
            "tables",
            "groups",
            "form_items",
            "key_value_items",
        ):
            for item in document.get(collection, []):
                reference = str(item.get("self_ref", ""))
                if reference:
                    all_items[reference] = item

        ordered_references = self._ordered_document_references(document, all_items)
        page_sizes: dict[int, tuple[float, float]] = {}
        for page_key, page_value in (document.get("pages") or {}).items():
            try:
                page_number = int(page_key)
            except (TypeError, ValueError):
                continue
            size = (page_value or {}).get("size") or {}
            try:
                page_sizes[page_number] = (
                    float(size.get("width", 0)),
                    float(size.get("height", 0)),
                )
            except (TypeError, ValueError):
                continue
        resolver: HeadingResolver | DoclingHierarchyResolver
        if self.settings.rule_based_headings:
            resolver = HeadingResolver(
                self._main_title_reference(all_items, ordered_references),
                all_items,
                ordered_references,
                page_sizes,
            )
        else:
            resolver = DoclingHierarchyResolver(
                self._main_title_reference(all_items, ordered_references),
                all_items,
                ordered_references,
            )
        resolved_labels: dict[str, str] = {}
        for reference in ordered_references:
            item = all_items.get(reference)
            if item is None:
                continue
            if isinstance(resolver, HeadingResolver):
                if resolver.is_chapter_contents(reference) or resolver.is_chapter_context(
                    reference
                ):
                    continue
                if (
                    (item.get("meta") or {}).get("konverter_exclude_from_output")
                    and not resolver.is_forced_structure(reference)
                ):
                    continue
            resolved_labels[reference] = resolver.label_for(item)
        blocks: list[dict[str, Any]] = []
        consumed: set[str] = set()

        def visit(reference: str) -> None:
            item = all_items.get(reference)
            if not item or reference in consumed:
                return
            consumed.add(reference)
            raw_label = _effective_raw_label(item)
            children = [
                str(child.get("$ref", "")) for child in item.get("children", [])
            ]

            is_forced_structure = (
                isinstance(resolver, HeadingResolver)
                and resolver.is_forced_structure(reference)
            )
            if (
                (item.get("meta") or {}).get("konverter_exclude_from_output")
                and not is_forced_structure
            ):
                return

            if resolver.is_chapter_contents(reference):
                return

            if resolver.is_chapter_context(reference):
                return

            if raw_label == "list" and children:
                child_items = [all_items.get(child) for child in children]
                child_items = self._ordered_list_items(
                    document,
                    [child for child in child_items if child],
                )
                consumed.update(child for child in children if child)
                list_entries = []
                for child in child_items:
                    value = str(child.get("text", "")).strip()
                    marker = str(child.get("marker", "")).strip()
                    list_entries.append(
                        {
                            "text": value,
                            "marker": marker,
                            "enumerated": bool(child.get("enumerated")),
                            "level": self._list_item_level(child),
                        }
                    )
                list_texts = [entry["text"] for entry in list_entries]
                confidences = [
                    confidence_by_ref.get(str(child.get("self_ref", "")))
                    for child in child_items
                ]
                valid_confidences = [
                    value for value in confidences if value is not None
                ]
                blocks.append(
                    {
                        "id": reference,
                        "label": "list",
                        "text": "\n".join(
                            (
                                f"{entry['marker']} {entry['text']}".strip()
                                if entry["marker"]
                                else f"• {entry['text']}"
                            )
                            for entry in list_entries
                            if entry["text"]
                        ),
                        "list_items": [value for value in list_texts if value],
                        "list_entries": [
                            entry for entry in list_entries if entry["text"]
                        ],
                        "page": _first_page(child_items[0]) if child_items else 1,
                        "confidence": min(valid_confidences)
                        if valid_confidences
                        else None,
                        "source_bounds": self._combined_source_bounds(
                            document, child_items
                        ),
                    }
                )
                return

            if raw_label in {"form_area", "key_value_area"} and children:
                child_items = [all_items.get(child) for child in children]
                child_items = [child for child in child_items if child]
                consumed.update(child for child in children if child)
                text = "\n".join(
                    str(child.get("text", "")).strip() for child in child_items
                )
                blocks.append(
                    {
                        "id": reference,
                        "label": "form",
                        "text": text,
                        "page": _first_page(child_items[0]) if child_items else 1,
                        "confidence": None,
                        "source_bounds": self._combined_source_bounds(
                            document, child_items
                        ),
                    }
                )
                return

            if raw_label in {"table", "document_index"}:
                table = self._table_data(item)
                caption = self._item_caption(item, all_items)
                if caption:
                    table["caption"] = caption
                blocks.append(
                    {
                        "id": reference,
                        "label": "document_index"
                        if raw_label == "document_index"
                        else "table",
                        "text": _plain_text_from_table(table),
                        "table_data": table,
                        "page": _first_page(item),
                        "confidence": confidence_by_ref.get(reference),
                        "source_bounds": self._combined_source_bounds(document, [item]),
                    }
                )
                return

            if raw_label == "group":
                return

            label = resolved_labels.get(reference) or resolver.label_for(item)
            text = (
                resolver.output_text(item)
                if isinstance(resolver, HeadingResolver)
                else str(item.get("text", "")).strip()
            )
            if label == "picture" and not text:
                text = str(item.get("caption", "")).strip()
            blocks.append(
                {
                    "id": reference,
                    "label": label,
                    "text": text,
                    "page": _first_page(item),
                    "confidence": confidence_by_ref.get(reference),
                    "source_bounds": self._combined_source_bounds(document, [item]),
                }
            )

        for reference in ordered_references:
            visit(reference)

        text_ranks = {
            str(item.get("self_ref", "")): index
            for index, item in enumerate(document.get("texts", []))
            if str(item.get("self_ref", ""))
        }
        rank_cache: dict[str, int] = {}

        def source_rank(reference: str, active: set[str] | None = None) -> int:
            if reference in text_ranks:
                return text_ranks[reference]
            if reference in rank_cache:
                return rank_cache[reference]
            active = set() if active is None else active
            if reference in active:
                return len(text_ranks) + len(rank_cache)
            active.add(reference)
            item = all_items.get(reference) or {}
            child_ranks = [
                source_rank(str(child.get("$ref", "")), active)
                for child in item.get("children", [])
                if str(child.get("$ref", ""))
            ]
            active.remove(reference)
            rank = min(child_ranks) if child_ranks else len(text_ranks) + len(rank_cache)
            rank_cache[reference] = rank
            return rank

        visible_blocks = [
            block
            for block in blocks
            if block["label"] not in {"header", "footer"} or block.get("text")
        ]
        original_block_order = {id(block): index for index, block in enumerate(visible_blocks)}
        visible_blocks.sort(
            key=lambda block: (
                int(block.get("page", 1)),
                source_rank(str(block.get("id", ""))),
                original_block_order[id(block)],
            )
        )
        ordered_blocks = [
            {**block, "order": index}
            for index, block in enumerate(visible_blocks)
        ]
        if self.settings.rule_based_headings:
            ordered_blocks = self._merge_split_chapter_titles(ordered_blocks)
        if not any(block["label"] == "title" for block in ordered_blocks):
            source_name = (
                str(document.get("name", "Document")).replace("_", " ").strip()
            )
            ordered_blocks.insert(
                0,
                {
                    "id": "#/synthetic/document-title",
                    "label": "title",
                    "text": source_name or "Document",
                    "page": 1,
                    "confidence": 1.0,
                    "order": 0,
                },
            )
            for index, block in enumerate(ordered_blocks):
                block["order"] = index
        return ordered_blocks

    @staticmethod
    def _list_item_level(item: dict[str, Any]) -> int:
        """Retain nesting supplied by the extractor without inventing levels."""
        metadata = item.get("meta") or {}
        for value in (
            item.get("level"),
            item.get("nesting_level"),
            metadata.get("level"),
            metadata.get("nesting_level"),
            metadata.get("indentation_level"),
        ):
            if isinstance(value, int):
                return max(0, value)
        return 0

    @staticmethod
    def _item_caption(
        item: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
    ) -> str:
        direct = str(item.get("caption") or "").strip()
        if direct:
            return direct
        values: list[str] = []
        for candidate in item.get("captions") or []:
            if isinstance(candidate, dict):
                reference = str(candidate.get("$ref", ""))
                value = str((all_items.get(reference) or {}).get("text", "")).strip()
            else:
                value = str(candidate).strip()
            if value:
                values.append(value)
        return " ".join(values)

    @classmethod
    def _ordered_list_items(
        cls,
        document: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Linearise multi-column list items by page, column, then vertical position."""
        eligible = [
            item
            for item in items
            if not (item.get("meta") or {}).get("konverter_exclude_from_output")
            and _effective_raw_label(item) not in {"page_header", "page_footer"}
        ]
        original_order = {id(item): index for index, item in enumerate(eligible)}
        pages: dict[int, list[tuple[dict[str, Any], dict[str, float] | None]]] = {}
        for item in eligible:
            page = _first_page(item)
            page_meta = document.get("pages", {}).get(
                str(page), document.get("pages", {}).get(page, {})
            )
            page_height = float(page_meta.get("size", {}).get("height", 0))
            provenance = item.get("prov") or []
            raw_box = provenance[0].get("bbox") if provenance else None
            bounds = cls._top_left_bbox(raw_box, page_height) if raw_box else None
            pages.setdefault(page, []).append((item, bounds))

        ordered: list[dict[str, Any]] = []
        for page in sorted(pages):
            page_entries = pages[page]
            bounded = [(item, box) for item, box in page_entries if box is not None]
            unbounded = [item for item, box in page_entries if box is None]
            page_meta = document.get("pages", {}).get(
                str(page), document.get("pages", {}).get(page, {})
            )
            page_width = float(page_meta.get("size", {}).get("width", 0))
            lefts = sorted(float(box["l"]) for _, box in bounded)
            split_threshold = max(48.0, page_width * 0.12)
            column_starts: list[float] = []
            for left in lefts:
                if not column_starts or left - column_starts[-1] > split_threshold:
                    column_starts.append(left)
                else:
                    column_starts[-1] = (column_starts[-1] + left) / 2

            columns: list[list[tuple[dict[str, Any], dict[str, float]]]] = [
                [] for _ in column_starts
            ]
            for item, box in bounded:
                assert box is not None
                column = min(
                    range(len(column_starts)),
                    key=lambda index: abs(float(box["l"]) - column_starts[index]),
                )
                columns[column].append((item, box))
            for column in columns:
                column.sort(
                    key=lambda value: (
                        float(value[1]["t"]),
                        float(value[1]["l"]),
                        original_order[id(value[0])],
                    )
                )
                ordered.extend(item for item, _ in column)
            ordered.extend(sorted(unbounded, key=lambda item: original_order[id(item)]))
        return ordered

    @staticmethod
    def _merge_split_chapter_titles(
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Join ``Chapter N`` and its same-page subtitle into one section title."""
        merged: list[dict[str, Any]] = []
        for block in blocks:
            if block.get("label") != "chapter_title_continuation":
                merged.append(block)
                continue
            previous = merged[-1] if merged else None
            if (
                previous is not None
                and previous.get("label") == "chapter_title"
                and int(previous.get("page", 1)) == int(block.get("page", 1))
            ):
                number = str(previous.get("text", "")).rstrip(" .:–—-")
                subtitle = str(block.get("text", "")).strip()
                previous["text"] = f"{number}: {subtitle}" if subtitle else number
                previous["confidence"] = min(
                    value
                    for value in (
                        previous.get("confidence"),
                        block.get("confidence"),
                        1.0,
                    )
                    if value is not None
                )
                continue
            block["label"] = "section_header_2"
            merged.append(block)
        for index, block in enumerate(merged):
            block["order"] = index
        return merged

    @staticmethod
    def _ordered_document_references(
        document: dict[str, Any],
        all_items: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Return stable extractor order, independent of hierarchy reparenting."""
        text_ranks = {
            str(item.get("self_ref", "")): index
            for index, item in enumerate(document.get("texts", []))
            if str(item.get("self_ref", ""))
        }
        rank_cache: dict[str, float] = {}

        def earliest_rank(reference: str, active: set[str] | None = None) -> float:
            if reference in text_ranks:
                return float(text_ranks[reference])
            if reference in rank_cache:
                return rank_cache[reference]
            active = set() if active is None else active
            if reference in active:
                return float(len(text_ranks) + len(rank_cache))
            active.add(reference)
            item = all_items.get(reference) or {}
            child_ranks = [
                earliest_rank(str(child.get("$ref", "")), active)
                for child in item.get("children", [])
                if str(child.get("$ref", ""))
            ]
            active.remove(reference)
            if child_ranks:
                rank = min(child_ranks) - 0.25
            else:
                page = _first_page(item)
                rank = len(text_ranks) + page
            rank_cache[reference] = rank
            return rank

        return sorted(
            all_items,
            key=lambda reference: (
                earliest_rank(reference),
                1 if reference in text_ranks else 0,
                reference,
            ),
        )

    @classmethod
    def _combined_source_bounds(
        cls,
        document: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not items:
            return None
        page = _first_page(items[0])
        page_meta = document.get("pages", {}).get(
            str(page),
            document.get("pages", {}).get(page, {}),
        )
        page_size = page_meta.get("size", {})
        page_width = float(page_size.get("width", 0))
        page_height = float(page_size.get("height", 0))
        boxes: list[dict[str, float]] = []
        for item in items:
            for provenance in item.get("prov") or []:
                if int(provenance.get("page_no", page)) != page:
                    continue
                raw_box = provenance.get("bbox")
                if raw_box:
                    boxes.append(cls._top_left_bbox(raw_box, page_height))
        if not boxes or page_width <= 0 or page_height <= 0:
            return None
        return {
            "left": min(box["l"] for box in boxes),
            "top": min(box["t"] for box in boxes),
            "right": max(box["r"] for box in boxes),
            "bottom": max(box["b"] for box in boxes),
            "page_width": page_width,
            "page_height": page_height,
        }

    @staticmethod
    def _main_title_reference(
        all_items: dict[str, dict[str, Any]],
        ordered_references: list[str],
    ) -> str | None:
        """Choose one early cover title; later Docling titles are chapters."""
        excluded = re.compile(
            r"^(?:contents|preface|terms of reference|glossary|recommendations?|"
            r"report\b|isbn\b|©|a community law reform project)",
            re.IGNORECASE,
        )
        address = re.compile(
            r"\b(?:gpo|po)\s+box\b|\b(?:victoria|melbourne)\s+\d{4}\b",
            re.IGNORECASE,
        )
        ranked: list[tuple[float, int, str]] = []
        for order, reference in enumerate(ordered_references):
            item = all_items.get(reference)
            if not item:
                continue
            if (item.get("meta") or {}).get("konverter_exclude_from_output"):
                continue
            raw_label = _effective_raw_label(item)
            if raw_label not in {"title", "section_header"}:
                continue
            page = _first_page(item)
            text = str(item.get("text", "")).strip()
            if page > 5 or not text or excluded.search(text) or address.search(text):
                continue
            metadata = item.get("meta") or {}
            font_size = metadata.get("hf__heading_font_size")
            score = (
                float(font_size) * 10 if isinstance(font_size, (int, float)) else 0.0
            )
            if raw_label == "title":
                score += 1000
            word_count = len(text.split())
            if 18 <= len(text) <= 120:
                score += 100
            if 3 <= word_count <= 14:
                score += 100
            if word_count <= 2:
                score -= 100
            score += min(len(text), 80) * 0.5
            ranked.append((score, -order, reference))
        return max(ranked, default=(0.0, 0, ""))[2] or None

    @staticmethod
    def _table_data(item: dict[str, Any]) -> dict[str, Any]:
        data = item.get("data", {})
        row_count = int(data.get("num_rows", 0))
        column_count = int(data.get("num_cols", 0))
        cells = data.get("table_cells") or [
            cell for row in data.get("grid", []) for cell in row
        ]
        if not row_count:
            row_count = (
                max(
                    (int(cell.get("start_row_offset_idx", 0)) for cell in cells),
                    default=-1,
                )
                + 1
            )
        if not column_count:
            column_count = (
                max(
                    (int(cell.get("start_col_offset_idx", 0)) for cell in cells),
                    default=-1,
                )
                + 1
            )
        row_count = max(1, row_count)
        column_count = max(1, column_count)
        matrix = [["" for _ in range(column_count)] for _ in range(row_count)]
        header_row = False
        for cell in cells:
            row = min(row_count - 1, int(cell.get("start_row_offset_idx", 0)))
            column = min(column_count - 1, int(cell.get("start_col_offset_idx", 0)))
            matrix[row][column] = str(cell.get("text", "")).strip()
            header_row = header_row or (row == 0 and bool(cell.get("column_header")))
        if header_row:
            return {"headers": matrix[0], "rows": matrix[1:]}
        return {
            "headers": [f"Column {index + 1}" for index in range(column_count)],
            "rows": matrix,
        }

    def _build_review_items(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for block in blocks:
            label = str(block.get("label", "unspecified"))
            if label in {"header", "footer"}:
                continue
            raw_confidence = block.get("confidence")
            confidence = float(raw_confidence) if raw_confidence is not None else 0.5
            if confidence >= self.settings.high_confidence_threshold:
                continue
            band = (
                "med"
                if confidence >= self.settings.medium_confidence_threshold
                else "low"
            )
            table_data = block.get("table_data")
            kind = "table" if label in {"table", "document_index"} else "text"
            display = LABEL_DISPLAY.get(label, label.replace("_", " ").title())
            page = int(block.get("page", 1))
            text = str(block.get("text", ""))
            source_text = html.escape(text[:1800]).replace("\n", "<br>")
            items.append(
                {
                    "id": f"review-{len(items) + 1}",
                    "block_id": block["id"],
                    "type": label,
                    "label": display,
                    "page": page,
                    "confidence": round(confidence, 4),
                    "band": band,
                    "title": f"{display} structure needs confirmation",
                    "kind": kind,
                    "status": "pending",
                    "extracted_text": None if kind == "table" else text,
                    "corrected_text": None,
                    "note": (
                        "Confirm the structure label and extracted content against the original PDF. "
                        "Changing the structure also changes the correction editor and generated output."
                    ),
                    "table_data": table_data if kind == "table" else None,
                    "corrected_table": None,
                    "source": {
                        "page": page,
                        "bounds": block.get("source_bounds"),
                        "html": (
                            f'<div class="hl" style="font-size:11px;line-height:1.55">{source_text or "[No text extracted]"}</div>'
                            f'<span class="page-num">Page {page}</span>'
                        ),
                    },
                }
            )
        return items
