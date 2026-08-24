from __future__ import annotations

import math
import hashlib
import copy
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import audit
from .config import Settings
from .exporter import build_accessible_html, build_json_ld, build_publication
from .logging_utils import document_logger, sanitize_for_log
from .media import render_pdf_region, render_pdf_regions
from .pipeline import LABEL_DISPLAY, KonverterPipeline, _plain_text_from_table
from .storage import LocalDocumentStore


def _table_from_text(value: str) -> dict[str, Any]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    parsed = [[cell.strip() for cell in re_split_row(line)] for line in lines]
    width = max((len(row) for row in parsed), default=1)
    parsed = [row + [""] * (width - len(row)) for row in parsed]
    if len(parsed) >= 2:
        return {"headers": parsed[0], "rows": parsed[1:]}
    return {
        "headers": [f"Column {index + 1}" for index in range(width)],
        "rows": parsed or [[""]],
    }


def re_split_row(value: str) -> list[str]:
    if "|" in value:
        return value.split("|")
    if "\t" in value:
        return value.split("\t")
    return [value]


ORDERED_LIST_MARKER_RE = re.compile(
    r"^(?P<marker>\((?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\)|"
    r"(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)])\s+"
)
BULLET_LIST_MARKER_RE = re.compile(r"^(?P<marker>[•\-–*·])\s+")


def _parse_list_line(line: str) -> dict[str, Any] | None:
    expanded = str(line).replace("\t", "  ").replace("|", " ").rstrip()
    indentation = len(expanded) - len(expanded.lstrip(" "))
    value = " ".join(expanded.strip().split())
    if not value:
        return None
    ordered = ORDERED_LIST_MARKER_RE.match(value)
    bullet = BULLET_LIST_MARKER_RE.match(value)
    match = ordered or bullet
    marker = match.group("marker") if match else ""
    text = value[match.end() :].strip() if match else value
    if not text:
        return None
    return {
        "text": text,
        "marker": marker,
        "enumerated": ordered is not None,
        "level": max(0, indentation // 2),
    }


def _strip_list_marker(line: str) -> str:
    entry = _parse_list_line(line)
    return str(entry.get("text", "")) if entry else ""


def _list_entries(value: str) -> list[dict[str, Any]]:
    return [
        entry
        for line in str(value).splitlines()
        if (entry := _parse_list_line(line)) is not None
    ]


def _list_items(value: str) -> list[str]:
    return [str(entry["text"]) for entry in _list_entries(value)]


def _table_list_marker(value: str) -> str:
    marker = " ".join(str(value).split())
    if re.fullmatch(
        r"\((?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\)|"
        r"(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)]",
        marker,
    ):
        return marker
    if re.fullmatch(r"\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+", marker):
        return f"{marker}."
    return ""


def _list_entries_from_table(
    table: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not table:
        return []
    rows = table.get("rows") or []
    if not rows:
        rows = [[value] for value in table.get("headers", []) if str(value).strip()]
    entries: list[dict[str, Any]] = []
    for row in rows:
        cells = [
            " ".join(str(value).replace("|", " ").split())
            for value in row
            if " ".join(str(value).replace("|", " ").split())
        ]
        if not cells:
            continue
        marker = _table_list_marker(cells[0]) if len(cells) > 1 else ""
        text = " — ".join(cells[1:] if marker else cells)
        parsed = _parse_list_line(text)
        if parsed is None:
            continue
        if marker:
            parsed["marker"] = marker
            parsed["enumerated"] = True
        entries.append(parsed)
    return entries


def _list_items_from_table(table: dict[str, Any] | None) -> list[str]:
    return [str(entry["text"]) for entry in _list_entries_from_table(table)]


def _is_generic_header(value: str) -> bool:
    return not value or bool(re.fullmatch(r"column\s+\d+", value, re.IGNORECASE))


SINGLE_LINE_TYPES = {
    "title",
    "caption",
    "section_header_1",
    "section_header_2",
    "section_header_3",
    "section_header_4",
    "section_header_5",
}


def _single_line(value: str) -> str:
    """Collapse list markers and line breaks into one clean heading line."""
    parts = [
        " ".join(_strip_list_marker(line).split()) for line in str(value).splitlines()
    ]
    return " ".join(part for part in parts if part).strip()


def _text_from_table(table: dict[str, Any] | None, target_type: str) -> str:
    """Convert table cells into the target structure without leaking delimiters."""
    if not table:
        return ""
    headers = [
        " ".join(str(value).replace("|", " ").split())
        for value in table.get("headers", [])
    ]
    rows = table.get("rows") or []
    cleaned_rows = [
        [" ".join(str(value).replace("|", " ").split()) for value in row]
        for row in rows
    ]
    cleaned_rows = [row for row in cleaned_rows if any(row)]
    if not cleaned_rows:
        cleaned_rows = [
            [value] for value in headers if value and not _is_generic_header(value)
        ]

    if target_type == "form":
        rendered = []
        for row in cleaned_rows:
            pairs = [
                f"{headers[index]}: {value}"
                if index < len(headers) and not _is_generic_header(headers[index])
                else value
                for index, value in enumerate(row)
                if value
            ]
            if pairs:
                rendered.append("\n".join(pairs))
        return "\n\n".join(rendered)

    if target_type == "footnote":
        rendered = []
        for row in cleaned_rows:
            facts = [
                f"{headers[index]}: {value}"
                if index < len(headers) and not _is_generic_header(headers[index])
                else value
                for index, value in enumerate(row)
                if value
            ]
            if facts:
                rendered.append("; ".join(facts).rstrip(".") + ".")
        return " ".join(rendered)

    rendered_rows = [
        " — ".join(value for value in row if value) for row in cleaned_rows
    ]
    return "\n".join(value for value in rendered_rows if value)


# Pictures, tables, and headings are too important to withhold from the
# approved output while a reviewer works through unrelated flagged items, so
# a pending/needs_attention item of one of these types no longer blocks
# approval. It still surfaces in the review list with its confidence badge.
# Footnotes are included for the same reason: they're low-stakes reference
# text, and the pipeline's own footnote/list classification (pipeline.py's
# _relabel_footnote_lists) means most of the volume in a legal document's
# review queue is citation apparatus rather than primary content.
NON_BLOCKING_REVIEW_TYPES = frozenset(
    {"picture", "table", "document_index", "footnote"}
)


def _is_blocking_review_item(item_type: str) -> bool:
    return item_type not in NON_BLOCKING_REVIEW_TYPES and not item_type.startswith(
        "section_header_"
    )


def _public_processing_error(error: Exception) -> str:
    """Map technical failures to stable, non-technical user guidance."""
    value = str(error).casefold()
    if isinstance(error, MemoryError) or any(
        token in value
        for token in ("out of memory", "bad_alloc", "paging file", "memoryerror")
    ):
        return (
            "The document could not be processed because the system ran out of "
            "available memory. Try processing fewer documents or disabling optional "
            "extraction features."
        )
    if any(token in value for token in ("password", "encrypted", "decrypt")):
        return (
            "This PDF is password-protected. Remove the password before uploading it."
        )
    if any(
        token in value
        for token in ("corrupt", "damaged", "truncated", "xref", "unexpected eof")
    ):
        return (
            "The PDF appears to be damaged or incomplete. Please open it locally to "
            "confirm that it works, then upload it again."
        )
    if any(
        token in value
        for token in ("connection", "network", "socket", "timed out", "timeout")
    ):
        return (
            "The connection was interrupted while processing the document. Please "
            "try again."
        )
    if any(token in value for token in ("unsupported", "not a pdf", "file type")):
        return "This file type is not supported. Please upload a PDF document."
    return (
        "Some content could not be extracted from this document. Try uploading "
        "another copy of the PDF."
    )


class ProcessingManager:
    def __init__(self, settings: Settings, store: LocalDocumentStore):
        self.settings = settings
        self.store = store
        self.pipeline = KonverterPipeline(settings)
        self.executor = ThreadPoolExecutor(
            max_workers=settings.worker_count,
            thread_name_prefix="konverter",
        )
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()

    def start(
        self,
        document_id: str,
        actor_id: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        record = self.store.get_record(document_id)
        current = record["job"]
        if current["state"] == "running":
            return self.status(document_id)

        with self._lock:
            self._cancelled.discard(document_id)
        self.store.delete_artifacts(
            document_id,
            "evidence-*.png",
            "metadata-evidence-*.png",
            "figure-*.png",
            "publication.json",
            "schema.jsonld",
            "structured.json",
            "accessible.html",
        )
        started_at = int(time.time() * 1000)
        estimate_seconds = self.store.estimate_seconds(
            int(record.get("pages", 0)),
            self.settings.baseline_seconds_per_page,
            self.settings.baseline_startup_seconds,
            self.settings.do_ocr,
        )
        job = {
            "state": "running",
            "started_at": started_at,
            "duration_ms": estimate_seconds * 1000,
            "current_step": 1,
            "progress": 1,
            "remaining_seconds": estimate_seconds,
            "message": "Preparing document",
        }
        self.store.update_record(
            document_id, job=job, approved_at=None, metadata_confirmed=False
        )
        self.executor.submit(self._run, document_id, actor_id, actor_email)
        return self.status(document_id)

    def stop(self, document_id: str) -> dict[str, Any]:
        with self._lock:
            self._cancelled.add(document_id)
        record = self.store.get_record(document_id)
        job = {
            **record["job"],
            "state": "idle",
            "started_at": None,
            "current_step": 0,
            "progress": 0,
            "remaining_seconds": 0,
            "message": "Processing stopped",
        }
        self.store.update_record(document_id, job=job)
        return job

    def status(self, document_id: str) -> dict[str, Any]:
        record = self.store.get_record(document_id)
        job = dict(record["job"])
        if job["state"] != "running" or job.get("started_at") is None:
            return job

        elapsed = max(0.0, time.time() - float(job["started_at"]) / 1000)
        estimate = max(1.0, float(job["duration_ms"]) / 1000)
        step = int(job.get("current_step", 0))
        stage_ranges = {
            0: (1, 5),
            1: (5, 10),
            2: (10, 65),
            3: (65, 78),
            4: (78, 86),
            5: (86, 92),
            6: (92, 99),
            7: (99, 99),
            8: (100, 100),
        }
        floor, ceiling = stage_ranges.get(step, (1, 99))
        time_progress = min(99, max(1, round(elapsed / estimate * 100)))
        job["progress"] = min(ceiling, max(floor, time_progress))
        job["remaining_seconds"] = max(1, math.ceil(estimate - elapsed))
        return job

    def _is_cancelled(self, document_id: str) -> bool:
        with self._lock:
            return document_id in self._cancelled

    def _set_stage(self, document_id: str, step: int, message: str) -> None:
        if self._is_cancelled(document_id):
            raise InterruptedError("Processing was stopped")
        # message is a static, developer-authored description (never extracted
        # document text), so it is safe to log as-is.
        document_logger(__name__, document_id).info("stage %s: %s", step, message)
        record = self.store.get_record(document_id)
        self.store.update_record(
            document_id,
            job={**record["job"], "current_step": step, "message": message},
        )

    def _run(
        self,
        document_id: str,
        actor_id: str | None = None,
        actor_email: str | None = None,
    ) -> None:
        log = document_logger(__name__, document_id)
        started = time.monotonic()
        log.info("processing started")
        try:
            output = self.pipeline.process(
                self.store.source_path(document_id),
                lambda step, message: self._set_stage(document_id, step, message),
            )
            if self._is_cancelled(document_id):
                log.info("processing stopped by user")
                return

            actual_seconds = max(output.elapsed_seconds, time.monotonic() - started)
            record = self._persist_output(document_id, output, actual_seconds)
            self.store.record_duration(
                int(record.get("pages", 0)),
                actual_seconds,
                self.settings.baseline_startup_seconds,
            )
            log.info(
                "processing completed in %.1fs (pages=%s)",
                actual_seconds,
                record.get("pages", 0),
            )
        except InterruptedError:
            log.info("processing stopped by user")
            return
        except Exception as exc:
            record = self.store.get_record(document_id)
            if record["job"]["state"] == "idle":
                return
            log.error("processing failed: %s", sanitize_for_log(exc))
            public_message = _public_processing_error(exc)
            self.store.update_record(
                document_id,
                job={
                    **record["job"],
                    "state": "failed",
                    "remaining_seconds": 0,
                    "message": public_message,
                },
            )
            audit.record_audit_sync(
                "process_failed",
                document_id=document_id,
                actor_id=actor_id,
                actor_email=actor_email,
                detail={"error": public_message, "file_name": record.get("file_name")},
            )

    def _persist_output(
        self,
        document_id: str,
        output: Any,
        actual_seconds: float,
    ) -> dict[str, Any]:
        self.store.write_artifacts(
            document_id,
            {
                "blocks.json": output.blocks,
                "review_items.json": output.review_items,
                "metadata.json": output.metadata_payload,
                "docling.json": output.raw_docling,
                "doc_confidence.json": output.doc_confidence,
                "warnings.json": output.warnings,
            },
        )

        record = self.store.get_record(document_id)
        metadata = output.metadata_payload["metadata"]
        job = {
            "state": "complete",
            "started_at": record["job"].get("started_at"),
            "duration_ms": max(1, round(actual_seconds * 1000)),
            "current_step": 8,
            "progress": 100,
            "remaining_seconds": 0,
            "message": "Ready for review",
        }
        return self.store.update_record(
            document_id,
            title=metadata.get("title") or record["title"],
            publisher=metadata.get("publisher") or record["publisher"],
            job=job,
        )


class WorkflowService:
    GENERATED_ARTIFACTS = (
        "publication.json",
        "schema.jsonld",
        "structured.json",
        "accessible.html",
    )

    def __init__(self, settings: Settings, store: LocalDocumentStore):
        self.settings = settings
        self.store = store
        self._review_update_lock = threading.RLock()

    def _discard_generated(self, document_id: str) -> None:
        self.store.delete_artifacts(document_id, *self.GENERATED_ARTIFACTS)
        self.store.update_record(document_id, approved_at=None)

    def get_review_items(self, document_id: str) -> list[dict[str, Any]]:
        items = self.store.read_artifact(document_id, "review_items.json")
        if items is None:
            raise RuntimeError("Review items are not ready yet")
        legacy_block_ids = {
            str(item.get("block_id", ""))
            for item in items
            if item.get("type") == "list_item"
        }
        legacy_box_ids = {
            str(item.get("block_id", ""))
            for item in items
            if item.get("type") == "callout"
        }
        if legacy_block_ids or legacy_box_ids:
            for item in items:
                if item.get("type") != "list_item":
                    continue
                item["type"] = "list"
                item["label"] = "List"
                item["title"] = "List structure needs confirmation"
            for item in items:
                if item.get("type") != "callout":
                    continue
                item["type"] = "box_section"
                item["label"] = "Box Section"
                item["title"] = "Box Section structure needs confirmation"
            blocks = self.store.read_artifact(document_id, "blocks.json", [])
            for block in blocks:
                if str(block.get("id", "")) in legacy_block_ids:
                    block["label"] = "list"
                if str(block.get("id", "")) in legacy_box_ids:
                    block["label"] = "box_section"
                    block["box_section_title"] = block.pop(
                        "callout_title", "Box Section"
                    )
                    block["box_section_kind"] = block.pop(
                        "callout_kind", "information"
                    )
                    block["box_section_blocks"] = block.pop(
                        "callout_blocks", []
                    )
            self.store.write_artifact(document_id, "review_items.json", items)
            self.store.write_artifact(document_id, "blocks.json", blocks)
        return items

    def processing_summary(self, document_id: str) -> dict[str, Any]:
        """Return document-level extraction coverage before final approval.

        The Review page must not depend on generated publication artifacts,
        because those do not exist until the final system-check confirmation.
        Counts therefore come from the reviewed block artifact and are paired
        with still-open review flags for the same element category.
        """

        record = self.store.get_record(document_id)
        blocks = self.store.read_artifact(document_id, "blocks.json", [])
        items = self.get_review_items(document_id)

        def walk(values: list[dict[str, Any]]):
            for value in values:
                yield value
                children = value.get("box_section_blocks") or value.get("blocks")
                if isinstance(children, list):
                    yield from walk(children)

        element_ids: dict[str, set[str]] = {
            "headings": set(),
            "images": set(),
            "tables": set(),
        }
        for index, block in enumerate(walk(blocks)):
            label = str(block.get("label", ""))
            block_id = str(block.get("id") or f"block-{index}")
            if label.startswith("section_header_"):
                category = "headings"
            elif label == "picture":
                category = "images"
            elif label == "table":
                category = "tables"
            else:
                continue
            element_ids[category].add(block_id)

        open_statuses = {"pending", "needs_attention"}
        needs_review: dict[str, set[str]] = {
            key: set() for key in element_ids
        }
        for item in items:
            if str(item.get("status", "pending")) not in open_statuses:
                continue
            item_type = str(item.get("type", ""))
            block_id = str(item.get("block_id") or item.get("id", ""))
            if item_type.startswith("section_header_"):
                category = "headings"
            elif item_type == "picture":
                category = "images"
            elif item_type == "table":
                category = "tables"
            else:
                continue
            needs_review[category].add(block_id)

        def coverage(category: str) -> dict[str, int]:
            total = len(element_ids[category])
            pending = min(total, len(needs_review[category]))
            return {
                "detected": max(0, total - pending),
                "total": total,
                "needs_review": pending,
            }

        page_total = max(0, int(record.get("pages", 0)))
        return {
            "pages": {
                "detected": page_total,
                "total": page_total,
                "needs_review": 0,
            },
            "headings": coverage("headings"),
            "images": coverage("images"),
            "tables": coverage("tables"),
        }

    def update_review_item(
        self,
        document_id: str,
        item_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        with self._review_update_lock:
            items = self.get_review_items(document_id)
            blocks = self.store.read_artifact(document_id, "blocks.json", [])
            item = self._apply_review_item_changes(items, blocks, item_id, changes)
            self.store.write_artifacts(
                document_id,
                {"blocks.json": blocks, "review_items.json": items},
            )
            self._discard_generated(document_id)
            return item

    @staticmethod
    def _apply_review_item_changes(
        items: list[dict[str, Any]],
        blocks: list[dict[str, Any]],
        item_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply one review patch to already-loaded artifacts.

        Keeping mutation separate from persistence lets a bulk request update
        every selected item in memory and publish the two artifacts once.
        """

        item = next((value for value in items if value["id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        block = next(
            (value for value in blocks if value["id"] == item["block_id"]), None
        )
        if block is None:
            raise KeyError(item["block_id"])

        target_type = changes.get("type") or item["type"]
        original_type = item["type"]
        if "type" in changes and changes["type"] is not None:
            block["label"] = target_type
            item["type"] = target_type
            item["label"] = changes.get("label") or LABEL_DISPLAY.get(
                target_type, target_type
            )
            item["title"] = f"{item['label']} structure needs confirmation"

        if target_type != "box_section":
            block.pop("box_section_title", None)
            block.pop("box_section_kind", None)
            block.pop("box_section_blocks", None)
            block.pop("callout_title", None)
            block.pop("callout_kind", None)
            block.pop("callout_blocks", None)
        elif original_type != "box_section":
            child = copy.deepcopy(block)
            child["label"] = original_type
            for key in (
                "box_section_title",
                "box_section_kind",
                "box_section_blocks",
                "callout_title",
                "callout_kind",
                "callout_blocks",
            ):
                child.pop(key, None)
            block["box_section_title"] = "Box Section"
            block["box_section_kind"] = "information"
            block["box_section_blocks"] = [child]

        target_is_table = target_type in {"table", "document_index"}
        if target_type == "box_section":
            children = block.get("box_section_blocks") or []
            if changes.get("corrected_text") is not None and len(children) == 1:
                children[0]["text"] = str(changes["corrected_text"])
            block["text"] = "\n\n".join(
                str(child.get("text", "")).strip()
                for child in children
                if str(child.get("text", "")).strip()
            )
            block.pop("table_data", None)
            block.pop("list_items", None)
            block.pop("list_entries", None)
            item["corrected_text"] = block["text"]
            item["corrected_table"] = None
        elif target_is_table:
            table = changes.get("corrected_table")
            if table is None:
                table = block.get("table_data") or _table_from_text(
                    changes.get("corrected_text") or block.get("text", "")
                )
            block["table_data"] = table
            block["text"] = _plain_text_from_table(table)
            block.pop("list_items", None)
            block.pop("list_entries", None)
            item["corrected_table"] = table
            item["corrected_text"] = None
        elif target_type == "list":
            text = changes.get("corrected_text")
            if text is None and original_type == "list" and block.get("list_entries"):
                list_entries = [dict(entry) for entry in block["list_entries"]]
            elif text is None:
                list_entries = _list_entries_from_table(
                    block.get("table_data")
                ) or _list_entries(str(block.get("text", "")))
            else:
                list_entries = _list_entries(str(text))
            list_items = [str(entry.get("text", "")) for entry in list_entries]
            text = "\n".join(
                f"{entry.get('marker', '')} {entry.get('text', '')}".strip()
                for entry in list_entries
                if str(entry.get("text", "")).strip()
            )
            block["text"] = text
            block.pop("table_data", None)
            block["list_items"] = list_items
            block["list_entries"] = list_entries
            item["corrected_text"] = text
            item["corrected_table"] = None
        else:
            text = changes.get("corrected_text")
            if text is None:
                text = (
                    _text_from_table(block.get("table_data"), target_type)
                    if block.get("table_data")
                    else block.get("text", "")
                )
            if target_type in SINGLE_LINE_TYPES:
                text = _single_line(text)
            block["text"] = text
            block.pop("table_data", None)
            block.pop("list_items", None)
            block.pop("list_entries", None)
            item["corrected_text"] = text
            item["corrected_table"] = None

        if changes.get("status") is not None:
            item["status"] = changes["status"]
        elif any(
            key in changes for key in ("type", "corrected_text", "corrected_table")
        ):
            item["status"] = "edited"
        block["removed"] = item["status"] == "removed"
        return item

    def resolve_all(self, document_id: str) -> list[dict[str, Any]]:
        with self._review_update_lock:
            items = self.get_review_items(document_id)
            for item in items:
                if item["status"] in {"pending", "needs_attention"}:
                    item["status"] = "accepted"
            self.store.write_artifact(document_id, "review_items.json", items)
            self._discard_generated(document_id)
            return items

    def update_review_items(
        self,
        document_id: str,
        item_ids: list[str],
        changes: dict[str, Any],
    ) -> list[dict[str, Any]]:
        with self._review_update_lock:
            unique_ids = list(dict.fromkeys(item_ids))
            items = self.get_review_items(document_id)
            blocks = self.store.read_artifact(document_id, "blocks.json", [])
            available = {item["id"] for item in items}
            missing = [item_id for item_id in unique_ids if item_id not in available]
            if missing:
                raise KeyError(missing[0])

            updated = [
                self._apply_review_item_changes(items, blocks, item_id, changes)
                for item_id in unique_ids
            ]
            self.store.write_artifacts(
                document_id,
                {"blocks.json": blocks, "review_items.json": items},
            )
            self._discard_generated(document_id)
            return updated

    def get_metadata(self, document_id: str) -> dict[str, Any]:
        payload = self.store.read_artifact(document_id, "metadata.json")
        if payload is None:
            raise RuntimeError("Metadata is not ready yet")
        normalised = {**payload}
        fields = dict(normalised.get("fields") or {})
        if "publishedDate" not in fields and "published_date" in fields:
            fields["publishedDate"] = fields.pop("published_date")
        normalised["fields"] = fields
        return normalised

    def save_metadata(
        self, document_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        payload = self.get_metadata(document_id)
        payload["metadata"] = metadata
        self.store.write_artifact(document_id, "metadata.json", payload)
        record = self.store.get_record(document_id)
        self._discard_generated(document_id)
        self.store.update_record(
            document_id,
            title=metadata.get("title") or record["title"],
            publisher=metadata.get("publisher") or record["publisher"],
            metadata_confirmed=True,
        )
        return metadata

    def approve(self, document_id: str) -> str:
        items = self.get_review_items(document_id)
        pending = [
            item
            for item in items
            if item["status"] in {"pending", "needs_attention"}
            and _is_blocking_review_item(str(item.get("type", "")))
        ]
        if pending:
            raise ValueError(f"{len(pending)} review item(s) are still unresolved")
        record = self.store.get_record(document_id)
        if not record.get("metadata_confirmed"):
            raise ValueError(
                "Confirm the document metadata on the metadata page before approval"
            )
        metadata_payload = self.get_metadata(document_id)
        metadata = metadata_payload["metadata"]
        if (
            not str(metadata.get("title", "")).strip()
            or not str(metadata.get("publisher", "")).strip()
        ):
            raise ValueError("Title and publisher must be confirmed before approval")

        blocks = self.store.read_artifact(document_id, "blocks.json", [])
        publication = build_publication(
            blocks,
            record,
            summary_max_chars=self.settings.description_max_chars,
        )

        def raw_blocks(values: list[dict[str, Any]]):
            for value in values:
                yield value
                yield from raw_blocks(
                    value.get("box_section_blocks")
                    or value.get("callout_blocks")
                    or []
                )

        def publication_blocks(values: list[dict[str, Any]]):
            for value in values:
                yield value
                if value.get("type") in {"box_section", "callout"}:
                    yield from publication_blocks(value.get("blocks") or [])

        block_by_id = {
            str(block.get("id", "")): block for block in raw_blocks(blocks)
        }
        figure_jobs: list[dict[str, Any]] = []
        pending_figures: list[tuple[dict[str, Any], str, Any]] = []
        for section in publication.get("sections", []):
            for figure in publication_blocks(section.get("blocks", [])):
                if figure.get("type") != "figure":
                    continue
                source_block = block_by_id.get(str(figure.get("sourceBlockId", "")))
                if source_block is None:
                    continue
                image_key = hashlib.sha256(
                    str(source_block.get("id", "")).encode("utf-8")
                ).hexdigest()[:16]
                destination = self.store.artifact_path(
                    document_id,
                    f"figure-{image_key}.png",
                )
                if destination.exists():
                    figure["imageKey"] = image_key
                    continue
                figure_jobs.append(
                    {
                        "destination": destination,
                        "page": int(source_block.get("page", 1)),
                        "bounds": source_block.get("source_bounds"),
                        "dpi": 168,
                        "padding": 18,
                    }
                )
                pending_figures.append((figure, image_key, destination))
        if figure_jobs:
            rendered = set(
                render_pdf_regions(self.store.source_path(document_id), figure_jobs)
            )
            for figure, image_key, destination in pending_figures:
                if destination in rendered:
                    figure["imageKey"] = image_key
        document_logger(__name__, document_id).info("generating JSON-LD (Schema.org)")
        json_ld = build_json_ld(
            document_id,
            publication,
            metadata,
            site_url=self.settings.site_url,
            site_name=self.settings.site_name,
            page_url_template=self.settings.page_url_template,
            public_api_url=self.settings.public_api_url,
            license_url=self.settings.default_license_url,
            copyright_holder=self.settings.default_copyright_holder,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        project_root = Path(__file__).resolve().parents[2]
        cover_path = self.store.cover_path(document_id)
        if not cover_path.exists():
            try:
                render_pdf_region(
                    self.store.source_path(document_id),
                    cover_path,
                    1,
                    dpi=120,
                    padding=0,
                )
            except Exception:
                cover_path.unlink(missing_ok=True)
        accessible_html = build_accessible_html(
            document_id,
            publication,
            metadata,
            json_ld,
            cover_path,
            project_root / "public" / "vlrc_logo.png",
            self.store.document_dir(document_id),
        )
        self.store.write_artifacts(
            document_id,
            {
                "publication.json": publication,
                "schema.jsonld": json_ld,
                "structured.json": {
                    "document": record,
                    "metadata": metadata,
                    "publication": publication,
                    "blocks": blocks,
                },
            },
        )
        self.store.write_text_artifact(document_id, "accessible.html", accessible_html)
        approved_at = datetime.now(timezone.utc).isoformat()
        self.store.update_record(document_id, approved_at=approved_at)
        return approved_at

    def revoke(self, document_id: str) -> None:
        self._discard_generated(document_id)

    def _document_confidence(self, document_id: str) -> dict[str, Any] | None:
        doc_confidence = (
            self.store.read_artifact(document_id, "doc_confidence.json", {}) or {}
        )
        score = doc_confidence.get("mean_score")
        source = "Mean document confidence"
        if score is None:
            blocks = self.store.read_artifact(document_id, "blocks.json", [])
            values = [
                float(block["confidence"])
                for block in blocks
                if block.get("confidence") is not None
            ]
            if not values:
                return None
            score = sum(values) / len(values)
            source = "Mean layout-cluster confidence"
        score = float(score)
        band = (
            "high"
            if score >= self.settings.high_confidence_threshold
            else "med"
            if score >= self.settings.medium_confidence_threshold
            else "low"
        )
        return {"score": round(score, 4), "band": band, "source": source}

    def chat_context_source(self, document_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """(structured, json_ld) for the chat assistant's context.

        Available as soon as processing completes, not just after approval —
        reviewers working through a long queue are exactly who benefits most
        from being able to ask about the document while still reviewing it.
        Once the document is approved, prefers the finished
        structured.json/schema.jsonld exports (the polished, final version);
        before that, builds the same shape on the fly from the current
        blocks.json, which review edits are written back into live as they
        happen, so corrections are reflected immediately.
        """
        record = self.store.get_record(document_id)
        if record.get("approved_at"):
            structured = self.store.read_artifact(document_id, "structured.json", {})
            json_ld = self.store.read_artifact(document_id, "schema.jsonld", {})
            if structured:
                return structured, json_ld
        blocks = self.store.read_artifact(document_id, "blocks.json", [])
        structured = {
            "metadata": self.get_metadata(document_id)["metadata"],
            "publication": build_publication(
                blocks, record, summary_max_chars=self.settings.description_max_chars
            ),
        }
        return structured, {}

    def publication_payload(self, document_id: str) -> dict[str, Any]:
        record = self.store.get_record(document_id)
        if not record.get("approved_at"):
            raise ValueError(
                "Approve the document before opening the publication preview"
            )
        return {
            "publication": self.store.read_artifact(
                document_id, "publication.json", {}
            ),
            "metadata": self.get_metadata(document_id)["metadata"],
            "json_ld": self.store.read_artifact(document_id, "schema.jsonld", {}),
            "confidence": self._document_confidence(document_id),
        }
