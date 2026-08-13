from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


async def _post(path: str, row: dict[str, Any], *, upsert: bool = False) -> None:
    if not SUPABASE_URL or not SERVICE_KEY:
        log.warning("audit: Supabase not configured; skipping %s", path)
        return
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    params: dict[str, str] | None = None
    if upsert:
        headers["Prefer"] = "resolution=merge-duplicates"
        params = {"on_conflict": "id"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{SUPABASE_URL}/rest/v1/{path}",
                headers=headers,
                params=params,
                json=row,
            )
        if response.status_code >= 300:
            log.warning(
                "audit: %s write failed: %s %s", path, response.status_code, response.text
            )
    except Exception as exc:
        log.warning("audit: %s write error: %s", path, exc)


async def record_document(document_id: str, filename: str, uploaded_by: str | None) -> None:
    """Mirror an uploaded document into Supabase so audit_log's FK resolves.

    The app's real document storage is local (LocalDocumentStore); this row
    only exists so audit_log has something to point at.
    """
    await _post(
        "documents",
        {
            "id": document_id,
            "filename": filename,
            "uploaded_by": uploaded_by,
            "status": "uploaded",
        },
        upsert=True,
    )


async def record_audit(
    action: str,
    *,
    document_id: str | None = None,
    actor_id: str | None = None,
    actor_email: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Insert one audit_log row. Never raises — failures are logged and swallowed
    so the caller's actual action always succeeds or fails on its own merits.
    """
    await _post(
        "audit_log",
        {
            "action": action,
            "document_id": document_id,
            "actor_id": actor_id,
            "actor_email": actor_email,
            "detail": detail,
        },
    )


async def list_recent(limit: int = 100) -> list[dict[str, Any]]:
    """Fetch the most recent audit_log rows, newest first. Read-only convenience
    for verification; returns [] if Supabase isn't configured or the read fails.
    """
    if not SUPABASE_URL or not SERVICE_KEY:
        log.warning("audit: Supabase not configured; returning empty audit log")
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/audit_log",
                headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"},
                params={"order": "id.desc", "limit": str(limit)},
            )
        if response.status_code >= 300:
            log.warning("audit: list failed: %s %s", response.status_code, response.text)
            return []
        return response.json()
    except Exception as exc:
        log.warning("audit: list error: %s", exc)
        return []
