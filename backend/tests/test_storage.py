from __future__ import annotations

import os
from pathlib import Path

from app.storage import LocalDocumentStore


def test_json_publish_retries_a_brief_windows_sharing_violation(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "review_items.json"
    real_replace = os.replace
    attempts = 0

    def briefly_locked(source: str | Path, destination: str | Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(5, "Access is denied")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", briefly_locked)

    LocalDocumentStore._write_json(target, [{"id": "review-1"}])

    assert target.read_text(encoding="utf-8") == '[{"id":"review-1"}]'
    assert attempts == 3
    assert not list(tmp_path.glob("*.tmp"))
