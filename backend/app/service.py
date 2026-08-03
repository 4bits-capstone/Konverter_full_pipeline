from __future__ import annotations

import math
import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .exporter import build_accessible_html, build_json_ld, build_publication
from .logging_utils import document_logger, sanitize_for_log
from .media import render_pdf_region, render_pdf_regions, render_pdf_regions
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


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^\s*(?:[•\-–*]|\d+[.)])\s*", "", line)


def _list_items(value: str) -> list[str]:
    return [
        " ".join(_strip_list_marker(line).replace("|", " ").split())
        for line in value.splitlines()
        if " ".join(_strip_list_marker(line).replace("|", " ").split())
    ]


def _list_items_from_table(table: dict[str, Any] | None) -> list[str]:
    if not table:
        return []
    rows = table.get("rows") or []
    if not rows:
        rows = [[value] for value in table.get("headers", []) if str(value).strip()]
    items: list[str] = []
    for row in rows:
        cells = [
            " ".join(str(value).replace("|", " ").split())
            for value in row
            if " ".join(str(value).replace("|", " ").split())
        ]
        if cells:
            items.append(" — ".join(cells))
    return items


def _is_generic_header(value: str) -> bool:
    return not value or bool(re.fullmatch(r"column\s+\d+", value, re.IGNORECASE))


SINGLE_LINE_TYPES = {
    "title",
    "chapter_title",
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

    def start(self, document_id: str) -> dict[str, Any]:
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
            "current_step": 0,
            "progress": 1,
            "remaining_seconds": estimate_seconds,
            "message": "Queued for extraction",
        }
        self.store.update_record(
            document_id, job=job, approved_at=None, metadata_confirmed=False
        )
        self.executor.submit(self._run, document_id)
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
            1: (5, 76),
            2: (60, 82),
            3: (70, 86),
            4: (78, 94),
            5: (94, 99),
            6: (100, 100),
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

    def _run(self, document_id: str) -> None:
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
            self.store.update_record(
                document_id,
                job={
                    **record["job"],
                    "state": "failed",
                    "remaining_seconds": 0,
                    "message": str(exc),
                },
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
            "current_step": 6,
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
        if legacy_block_ids:
            for item in items:
                if item.get("type") != "list_item":
                    continue
                item["type"] = "list"
                item["label"] = "List"
                item["title"] = "List structure needs confirmation"
            blocks = self.store.read_artifact(document_id, "blocks.json", [])
            for block in blocks:
                if str(block.get("id", "")) in legacy_block_ids:
                    block["label"] = "list"
            self.store.write_artifact(document_id, "review_items.json", items)
            self.store.write_artifact(document_id, "blocks.json", blocks)
        return items

    def update_review_item(
        self,
        document_id: str,
        item_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        items = self.get_review_items(document_id)
        blocks = self.store.read_artifact(document_id, "blocks.json", [])
        item = next((value for value in items if value["id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        block = next(
            (value for value in blocks if value["id"] == item["block_id"]), None
        )
        if block is None:
            raise KeyError(item["block_id"])

        target_type = changes.get("type") or item["type"]
        if "type" in changes and changes["type"] is not None:
            block["label"] = target_type
            item["type"] = target_type
            item["label"] = changes.get("label") or LABEL_DISPLAY.get(
                target_type, target_type
            )
            item["title"] = f"{item['label']} structure needs confirmation"

        target_is_table = target_type in {"table", "document_index"}
        if target_is_table:
            table = changes.get("corrected_table")
            if table is None:
                table = block.get("table_data") or _table_from_text(
                    changes.get("corrected_text") or block.get("text", "")
                )
            block["table_data"] = table
            block["text"] = _plain_text_from_table(table)
            block.pop("list_items", None)
            item["kind"] = "table"
            item["corrected_table"] = table
            item["corrected_text"] = None
        elif target_type == "list":
            text = changes.get("corrected_text")
            if text is None:
                list_items = _list_items_from_table(
                    block.get("table_data")
                ) or _list_items(str(block.get("text", "")))
            else:
                list_items = _list_items(str(text))
            text = "\n".join(list_items)
            block["text"] = text
            block.pop("table_data", None)
            block["list_items"] = list_items
            item["kind"] = "text"
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
            item["kind"] = "text"
            item["corrected_text"] = text
            item["corrected_table"] = None

        if changes.get("status") is not None:
            item["status"] = changes["status"]
        elif any(
            key in changes for key in ("type", "corrected_text", "corrected_table")
        ):
            item["status"] = "edited"
        block["removed"] = item["status"] == "removed"

        self.store.write_artifact(document_id, "blocks.json", blocks)
        self.store.write_artifact(document_id, "review_items.json", items)
        self._discard_generated(document_id)
        return item

    def resolve_all(self, document_id: str) -> list[dict[str, Any]]:
        items = self.get_review_items(document_id)
        for item in items:
            if item["status"] in {"pending", "needs_attention"}:
                item["status"] = "accepted"
        self.store.write_artifact(document_id, "review_items.json", items)
        self._discard_generated(document_id)
        return items

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
            item for item in items if item["status"] in {"pending", "needs_attention"}
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
        publication = build_publication(blocks, record)
        block_by_id = {str(block.get("id", "")): block for block in blocks}
        figure_jobs: list[dict[str, Any]] = []
        pending_figures: list[tuple[dict[str, Any], str, Any]] = []
        for section in publication.get("sections", []):
            for figure in section.get("blocks", []):
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
        source = "Docling mean confidence"
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
