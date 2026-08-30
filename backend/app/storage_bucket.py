from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .auth import SUPABASE_ANON_KEY
from .config import Settings

_lock = threading.Lock()
_client_cache: dict[tuple[str, str], Any] = {}


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


def signed_upload_target(settings: Settings, object_key: str, ttl: int) -> dict[str, Any]:
    """Build a {"url", "headers"} PUT target for the worker.

    Supabase's signed-upload PUT endpoint sits behind the project's API
    gateway, which rejects requests with no `apikey` header even though the
    signed `token` in the URL is what actually authorises the write. We use
    the public anon key here (safe to hand to the worker) rather than the
    service-role key used to mint the token, so the worker never receives a
    credential more powerful than what's already shipped to the frontend.
    ttl is accepted for interface symmetry with signed_download_url, but
    Supabase's create_signed_upload_url does not accept a custom expiry.
    """
    from storage3.types import CreateSignedUploadUrlOptions

    response = _bucket(settings).create_signed_upload_url(
        object_key, CreateSignedUploadUrlOptions(upsert="true")
    )
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
