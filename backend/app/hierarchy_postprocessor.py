"""Konverter's patched docling-hierarchical-pdf postprocessor.

This module is based on ``hierarchical.postprocessor`` from
docling-hierarchical-pdf 0.1.8.  It keeps the user's bounded promotion of
numbered list items and the linear structural pass, while fixing parent-state
leakage and leaving page furniture outside the reconstructed content tree.
"""

from functools import cached_property
from io import BytesIO
from pathlib import PurePath
from typing import Optional, Union

from docling.datamodel.base_models import DocumentStream
from docling.datamodel.document import ConversionResult
from docling_core.types.doc.document import (
    DocItem,
    DocItemLabel,
    DoclingDocument,
    ListItem,
    NodeItem,
    RefItem,
    SectionHeaderItem,
    TextItem,
)

from hierarchical.hierarchy_builder import create_toc
from hierarchical.hierarchy_builder_metadata import HierarchyBuilderMetadata
from hierarchical.parsers import (
    infer_header_level_letter,
    infer_header_level_numerical,
    infer_header_level_roman,
)
from hierarchical.types.hierarchical_header import HierarchicalHeader


class DoclingResultNotReadyException(Exception):
    def __init__(self) -> None:
        super().__init__(
            "It seems that the Docling result is not ready for postprocessing."
        )


class ItemNotRegisteredAsChildException(Exception):
    def __init__(self, item: NodeItem):
        super().__init__(f"The item {item} is not registered as a child of its parent.")


class ItemInconsistencyException(Exception):
    pass


def flatten_hierarchy_tree(
    node: HierarchicalHeader,
    parent_level: int = 0,
) -> list[tuple[HierarchicalHeader, int]]:
    children: list[tuple[HierarchicalHeader, int]] = []
    this_level = parent_level + 1
    for child in node.children:
        children.append((child, this_level))
        children.extend(flatten_hierarchy_tree(child, this_level))
    return children


def set_item_in_doc(doc: DoclingDocument, item: DocItem) -> None:
    _, path, index_text = item.self_ref.split("/")
    getattr(doc, path)[int(index_text)] = item


class ResultPostprocessor:
    """Infer heading depth and rewrite the Docling parent/child tree in place."""

    _MAX_HEADING_WORDS = 10
    _FURNITURE_LABELS = {DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER}

    def __init__(
        self,
        result: ConversionResult,
        source: Optional[Union[PurePath, str, DocumentStream, BytesIO]] = None,
        raise_on_error: bool = False,
    ) -> None:
        self.result = result
        self.source = source
        self.raise_on_error = raise_on_error

    @cached_property
    def has_hierarchy_levels(self) -> bool:
        return len({level for _, level in self.result.document.iterate_items()}) > 1

    @staticmethod
    def _is_list_item_header(item: ListItem) -> bool:
        text = (item.orig if item.orig else item.text).strip()
        if len(text.split()) > ResultPostprocessor._MAX_HEADING_WORDS:
            return False
        return bool(
            infer_header_level_numerical(text)
            or infer_header_level_letter(text)
            or infer_header_level_roman(text)
        )

    def _get_headers_result(self) -> list[dict]:
        items: list[dict] = []
        for item, _ in self.result.document.iterate_items():
            if not isinstance(item, SectionHeaderItem) and (
                not isinstance(item, ListItem) or not self._is_list_item_header(item)
            ):
                continue
            if not item.prov:
                continue
            provenance = item.prov[0]

            if isinstance(item, ListItem):
                text = item.orig if item.orig else item.text
                items.append(
                    {
                        "text": " ".join(text.splitlines()),
                        "font_size": provenance.bbox.height,
                        "is_bold": False,
                        "is_italic": False,
                        "top_left": provenance.bbox.t,
                        "text_direction:": None,
                        "font": "",
                        "reference": item.self_ref,
                    }
                )
                continue

            page = self.result.pages[provenance.page_no - 1]
            if page.predictions.layout is None:
                continue
            for cluster in page.predictions.layout.clusters:
                if not cluster or cluster.label != "section_header" or not cluster.cells:
                    continue
                first_cell = cluster.cells[0]
                if page.size is None:
                    raise DoclingResultNotReadyException()
                cell_box = first_cell.rect.to_bounding_box().to_bottom_left_origin(
                    page_height=page.size.height
                )
                overlap = provenance.bbox.intersection_area_with(cell_box)
                if overlap / max(cell_box.area(), 1e-6) < 0.8:
                    continue
                font_name = getattr(first_cell, "font_name", "") or ""
                font_parts = font_name.split("-", 1)
                style = font_parts[1] if len(font_parts) > 1 else ""
                items.append(
                    {
                        "text": " ".join(cell.text for cell in cluster.cells),
                        "font_size": first_cell.rect.height,
                        "is_bold": "Bold" in style,
                        "is_italic": "Italic" in style,
                        "top_left": first_cell.rect.r_y0,
                        "text_direction:": first_cell.text_direction,
                        "font": font_parts[0],
                        "reference": item.self_ref,
                    }
                )
                break
        return items

    def _get_headers_document(self) -> list[dict]:
        items: list[dict] = []
        for item, _ in self.result.document.iterate_items():
            if not isinstance(item, SectionHeaderItem) and (
                not isinstance(item, ListItem) or not self._is_list_item_header(item)
            ):
                continue
            if not item.prov:
                continue
            text = item.orig if isinstance(item, ListItem) and item.orig else item.text
            provenance = item.prov[0]
            items.append(
                {
                    "text": " ".join(text.splitlines()),
                    "font_size": provenance.bbox.height,
                    "is_bold": False,
                    "is_italic": False,
                    "top_left": provenance.bbox.t,
                    "text_direction:": None,
                    "font": "",
                    "reference": item.self_ref,
                }
            )
        return items

    def get_headers(self) -> list[dict]:
        return self._get_headers_result() or self._get_headers_document()

    def process(self) -> None:  # noqa: C901
        metadata_builder = HierarchyBuilderMetadata(
            self.result,
            self.source,
            self.raise_on_error,
        )
        header_correction = False
        if metadata_builder.toc:
            root = metadata_builder.infer()
            header_correction = bool(root.children)
        else:
            root = create_toc(self.get_headers())

        document = self.result.document
        flat_hierarchy = flatten_hierarchy_tree(root)
        by_reference = {
            node.doc_ref: (node, level)
            for node, level in flat_hierarchy
            if node.doc_ref
        }
        current_header = root
        current_level = 0

        # Freeze document order once. Structural moves only alter parents and do
        # not require the quadratic restart loop used by the upstream 0.1.8 code.
        for item, _ in list(document.iterate_items(with_groups=True)):
            if item.label in self._FURNITURE_LABELS:
                continue
            new_parent_ref: RefItem | None = None

            if (
                isinstance(item, SectionHeaderItem)
                and item.self_ref not in by_reference
                and header_correction
            ):
                item = TextItem(
                    label=DocItemLabel.TEXT,
                    **{
                        key: value
                        for key, value in item.model_dump().items()
                        if key != "label" and key in TextItem.model_fields
                    },
                )
                set_item_in_doc(document, item)

            if item.self_ref in by_reference:
                if not isinstance(item, SectionHeaderItem):
                    if not isinstance(item, (TextItem, ListItem)):
                        raise ItemInconsistencyException()
                    header_item = SectionHeaderItem(
                        **{
                            key: value
                            for key, value in item.model_dump().items()
                            if key != "label" and key in SectionHeaderItem.model_fields
                        }
                    )
                    if isinstance(item, ListItem):
                        header_item.text = item.orig or item.text
                    set_item_in_doc(document, header_item)
                    item = header_item

                current_header, current_level = by_reference[item.self_ref]
                item.level = current_level
                if current_header.parent and current_header.parent.doc_ref:
                    new_parent_ref = RefItem(cref=current_header.parent.doc_ref)
            elif current_header.doc_ref:
                if isinstance(item, SectionHeaderItem):
                    item.level = min(current_level + 1, 5)
                new_parent_ref = RefItem(cref=current_header.doc_ref)

            if new_parent_ref is None:
                continue
            if item.parent is None:
                raise ItemNotRegisteredAsChildException(item)
            if item.parent.cref == new_parent_ref.cref:
                continue

            old_parent = item.parent.resolve(document)
            new_parent = new_parent_ref.resolve(document)
            if old_parent is None or new_parent is None:
                raise ItemNotRegisteredAsChildException(item)
            item_index = next(
                (
                    index
                    for index, child in enumerate(old_parent.children)
                    if child.cref == item.self_ref
                ),
                None,
            )
            if item_index is None:
                raise ItemNotRegisteredAsChildException(item)
            child_ref = old_parent.children.pop(item_index)
            item.parent = new_parent_ref
            if not any(child.cref == child_ref.cref for child in new_parent.children):
                new_parent.children.append(child_ref)
