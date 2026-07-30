from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


class DocumentNotFoundError(KeyError):
    pass


class LocalDocumentStore:
    """Small filesystem repository used until a database is introduced."""

    def __init__(self, root: Path):
        self.root = root
        self.documents_dir = root / "documents"
        self.metrics_path = root / "processing_metrics.json"
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def document_dir(self, document_id: str) -> Path:
        if not document_id or any(
            char
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
            for char in document_id
        ):
            raise DocumentNotFoundError(document_id)
        path = self.documents_dir / document_id
        if not path.is_dir():
            raise DocumentNotFoundError(document_id)
        return path

    def create_document(
        self, document_id: str, source_path: Path, record: dict[str, Any]
    ) -> Path:
        with self._lock:
            path = self.documents_dir / document_id
            path.mkdir(parents=True, exist_ok=False)
            destination = path / "source.pdf"
            os.replace(source_path, destination)
            self._write_json(path / "record.json", record)
            return path

    def get_record(self, document_id: str) -> dict[str, Any]:
        with self._lock:
            return self._read_json(self.document_dir(document_id) / "record.json")

    def update_record(self, document_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            path = self.document_dir(document_id) / "record.json"
            record = self._read_json(path)
            record.update(changes)
            record["updated_at"] = time.time()
            self._write_json(path, record)
            return record

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            path = self.document_dir(document_id)
            for child in path.iterdir():
                if child.is_file():
                    child.unlink()
            path.rmdir()

    def source_path(self, document_id: str) -> Path:
        return self.document_dir(document_id) / "source.pdf"

    def cover_path(self, document_id: str) -> Path:
        return self.document_dir(document_id) / "cover.png"

    def artifact_path(self, document_id: str, name: str) -> Path:
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("Invalid artifact name")
        return self.document_dir(document_id) / name

    def read_artifact(self, document_id: str, name: str, default: Any = None) -> Any:
        with self._lock:
            path = self.artifact_path(document_id, name)
            if not path.exists():
                return default
            return self._read_json(path)

    def write_artifact(self, document_id: str, name: str, value: Any) -> None:
        with self._lock:
            self._write_json(self.artifact_path(document_id, name), value)

    def write_artifacts(self, document_id: str, values: dict[str, Any]) -> None:
        with self._lock:
            directory = self.document_dir(document_id)
            for name, value in values.items():
                if "/" in name or "\\" in name or name.startswith("."):
                    raise ValueError("Invalid artifact name")
                self._write_json(directory / name, value)

    def write_text_artifact(self, document_id: str, name: str, value: str) -> None:
        with self._lock:
            path = self.artifact_path(document_id, name)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(value, encoding="utf-8")
            os.replace(temporary, path)

    def estimate_seconds(
        self,
        pages: int,
        baseline_seconds_per_page: float,
        baseline_startup_seconds: float,
        do_ocr: bool,
    ) -> int:
        metrics = (
            self._read_json(self.metrics_path) if self.metrics_path.exists() else {}
        )
        observed = float(metrics.get("seconds_per_page", baseline_seconds_per_page))
        startup = float(metrics.get("startup_seconds", baseline_startup_seconds))
        ocr_multiplier = 1.85 if do_ocr else 1.0
        return max(10, round(startup + max(1, pages) * observed * ocr_multiplier))

    def record_duration(
        self, pages: int, duration_seconds: float, baseline_startup_seconds: float
    ) -> None:
        if pages <= 0 or duration_seconds <= 0:
            return
        with self._lock:
            metrics = (
                self._read_json(self.metrics_path) if self.metrics_path.exists() else {}
            )
            old_rate = float(metrics.get("seconds_per_page", 0))
            sample_startup = min(baseline_startup_seconds, duration_seconds * 0.4)
            sample_rate = max(0.1, (duration_seconds - sample_startup) / pages)
            seconds_per_page = (
                sample_rate if old_rate <= 0 else old_rate * 0.7 + sample_rate * 0.3
            )
            old_startup = float(metrics.get("startup_seconds", 0))
            startup_seconds = (
                sample_startup
                if old_startup <= 0
                else old_startup * 0.7 + sample_startup * 0.3
            )
            self._write_json(
                self.metrics_path,
                {
                    "seconds_per_page": round(seconds_per_page, 4),
                    "startup_seconds": round(startup_seconds, 2),
                    "samples": int(metrics.get("samples", 0)) + 1,
                    "last_duration_seconds": round(duration_seconds, 2),
                    "last_pages": pages,
                },
            )

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(
                value,
                output,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        os.replace(temporary, path)
