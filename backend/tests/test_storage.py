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


def test_write_artifacts_rejects_a_path_traversal_name_same_as_write_artifact(
    tmp_path: Path,
) -> None:
    """write_artifacts used to re-implement artifact_path's name validation
    inline instead of calling it — the two checks could silently drift out
    of sync if one were updated (e.g. to block a new traversal pattern) and
    the other forgotten. Both entry points must reject the same names."""
    store = LocalDocumentStore(tmp_path)
    (store.documents_dir / "doc-1").mkdir(parents=True, exist_ok=True)

    for bad_name in ("../escape.json", "sub/dir.json", ".hidden.json"):
        try:
            store.artifact_path("doc-1", bad_name)
            raised_by_artifact_path = False
        except ValueError:
            raised_by_artifact_path = True
        try:
            store.write_artifacts("doc-1", {bad_name: {"value": 1}})
            raised_by_write_artifacts = False
        except ValueError:
            raised_by_write_artifacts = True
        assert raised_by_artifact_path is True
        assert raised_by_write_artifacts is True
