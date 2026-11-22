from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .auth import SUPABASE_ANON_KEY
from .config import Settings
from .logging_utils import document_logger, get_logger, sanitize_for_log

SUPABASE_SIGNED_UPLOAD_TTL_SECONDS = 7200
_LIST_PAGE_SIZE = 100
_REMOVE_BATCH_SIZE = 1000

log = get_logger("storage_bucket")
_lock = threading.Lock()
_client_cache: dict[tuple[str, str], Any] = {}


def is_configured(settings: Settings) -> bool:
    return bool(
        settings.supabase_url.strip()
        and settings.supabase_service_key.strip()
        and settings.storage_bucket.strip()
    )


def _client(settings: Settings) -> Any:
    key = (settings.supabase_url, settings.supabase_service_key)
    client = _client_cache.get(key)
    if client is not None:
        return client
    with _lock:
        client = _client_cache.get(key)
        if client is not None:
            return client
        from supabase import create_client

        client = create_client(settings.supabase_url, settings.supabase_service_key)
        _client_cache[key] = client
        return client


def _bucket(settings: Settings) -> Any:
    return _client(settings).storage.from_(settings.storage_bucket)


def upload_pdf(settings: Settings, document_id: str, local_path: Path) -> str:
    object_key = f"{document_id}/source.pdf"
    with open(local_path, "rb") as handle:
        _bucket(settings).upload(
            object_key,
            handle,
            {"content-type": "application/pdf", "upsert": "true"},
        )
    return object_key


def signed_download_url(settings: Settings, object_key: str, ttl: int) -> str:
    response = _bucket(settings).create_signed_url(object_key, ttl)
    return response["signedURL"]


def signed_upload_target(
    settings: Settings, object_key: str, ttl: int | None = None
) -> dict[str, Any]:
    """Build a {"url", "headers"} PUT target for the worker.

    Supabase's signed-upload PUT endpoint sits behind the project's API
    gateway, which rejects requests with no `apikey` header even though the
    signed `token` in the URL is what actually authorises the write. We use
    the public anon key here (safe to hand to the worker) rather than the
    service-role key used to mint the token, so the worker never receives a
    credential more powerful than what's already shipped to the frontend.
    ttl is accepted for interface symmetry with signed_download_url, but
    Supabase's create_signed_upload_url does not accept a custom expiry and
    always mints a token with a fixed 7,200s (2-hour) lifetime.
    """
    if ttl is not None and ttl > SUPABASE_SIGNED_UPLOAD_TTL_SECONDS:
        log.warning(
            "Requested signed upload TTL (%ds) exceeds Supabase's fixed %ds "
            "signed-upload URL expiry; jobs queued longer than %ds may fail upload.",
            ttl,
            SUPABASE_SIGNED_UPLOAD_TTL_SECONDS,
            SUPABASE_SIGNED_UPLOAD_TTL_SECONDS,
        )

    from storage3.types import CreateSignedUploadUrlOptions

    try:
        response = _bucket(settings).create_signed_upload_url(
            object_key, CreateSignedUploadUrlOptions(upsert="true")
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to create signed upload URL for '{object_key}' in bucket "
            f"'{settings.storage_bucket}': {exc}"
        ) from exc
    return {
        "url": response["signed_url"],
        "headers": {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        },
    }


def download_json(settings: Settings, object_key: str) -> dict[str, Any]:
    content = _bucket(settings).download(object_key)
    return json.loads(content)


def delete_objects(
    settings: Settings,
    object_keys: list[str],
    *,
    raise_on_error: bool = False,
) -> list[str]:
    keys = list(
        dict.fromkeys(
            key.strip().strip("/")
            for key in object_keys
            if isinstance(key, str) and key.strip().strip("/")
        )
    )
    if not keys or not is_configured(settings):
        return []

    bucket = _bucket(settings)
    removed: list[str] = []
    for start in range(0, len(keys), _REMOVE_BATCH_SIZE):
        batch = keys[start : start + _REMOVE_BATCH_SIZE]
        try:
            bucket.remove(batch)
            removed.extend(batch)
        except Exception as exc:
            log.warning(
                "Failed to delete %d remote storage object(s) from bucket %s: %s",
                len(batch),
                sanitize_for_log(settings.storage_bucket),
                sanitize_for_log(exc),
            )
            if raise_on_error:
                raise
    return removed


def _list_document_object_keys(bucket: Any, root_prefix: str) -> list[str]:
    pending_prefixes: list[str] = [root_prefix]
    visited_prefixes: set[str] = set()
    object_keys: list[str] = []

    while pending_prefixes:
        prefix = pending_prefixes.pop(0)
        if prefix in visited_prefixes:
            continue
        visited_prefixes.add(prefix)

        offset = 0
        seen_names_in_prefix: set[str] = set()
        while True:
            entries = bucket.list(
                prefix,
                {
                    "limit": _LIST_PAGE_SIZE,
                    "offset": offset,
                    "sortBy": {"column": "name", "order": "asc"},
                },
            )
            if not entries:
                break

            new_in_page = 0
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "").strip("/")
                if not name or name in {".", ".."}:
                    continue
                if name not in seen_names_in_prefix:
                    seen_names_in_prefix.add(name)
                    new_in_page += 1
                full_key = f"{prefix}/{name}"
                is_folder = (
                    ("id" in entry and entry["id"] is None)
                    or (
                        "metadata" in entry
                        and entry["metadata"] is None
                        and not entry.get("id")
                    )
                )
                if is_folder:
                    if full_key not in visited_prefixes:
                        pending_prefixes.append(full_key)
                else:
                    object_keys.append(full_key)

            if len(entries) < _LIST_PAGE_SIZE or (offset > 0 and new_in_page == 0):
                break
            offset += _LIST_PAGE_SIZE

    return object_keys


def delete_document_objects(settings: Settings, document_id: str) -> int:
    clean_id = (document_id or "").strip("/")
    if not clean_id or not is_configured(settings):
        return 0

    try:
        keys = _list_document_object_keys(_bucket(settings), clean_id)
    except Exception as exc:
        document_logger("storage_bucket", clean_id).warning(
            "Failed to list remote storage objects for cleanup: %s",
            sanitize_for_log(exc),
        )
        return 0

    if not keys:
        return 0
    removed = delete_objects(settings, keys, raise_on_error=False)
    return len(removed)
