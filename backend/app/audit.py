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


def record_audit_sync(
    action: str,
    *,
    document_id: str | None = None,
    actor_id: str | None = None,
    actor_email: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Sync twin of record_audit, for callers outside an event loop — the
    processing pipeline runs in a plain ThreadPoolExecutor thread, not
    asyncio, so it can't await. Same swallow-and-log failure behaviour."""
    if not SUPABASE_URL or not SERVICE_KEY:
        log.warning("audit: Supabase not configured; skipping audit_log")
        return
    row = {
        "action": action,
        "document_id": document_id,
        "actor_id": actor_id,
        "actor_email": actor_email,
        "detail": detail,
    }
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(
                f"{SUPABASE_URL}/rest/v1/audit_log",
                headers={
                    "apikey": SERVICE_KEY,
                    "Authorization": f"Bearer {SERVICE_KEY}",
                    "Content-Type": "application/json",
                },
                json=row,
            )
        if response.status_code >= 300:
            log.warning(
                "audit: audit_log write failed: %s %s", response.status_code, response.text
            )
    except Exception as exc:
        log.warning("audit: audit_log write error: %s", exc)


async def _get(params: dict[str, str]) -> list[dict[str, Any]]:
    if not SUPABASE_URL or not SERVICE_KEY:
        log.warning("audit: Supabase not configured; returning empty audit log")
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/audit_log",
                headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"},
                params=params,
            )
        if response.status_code >= 300:
            log.warning("audit: list failed: %s %s", response.status_code, response.text)
            return []
        return response.json()
    except Exception as exc:
        log.warning("audit: list error: %s", exc)
        return []


DEFAULT_PAGE_LIMIT = 500
MAX_PAGE_LIMIT = 2000


async def list_recent(limit: int = DEFAULT_PAGE_LIMIT, offset: int = 0) -> list[dict[str, Any]]:
    """Fetch audit_log rows across all users, newest first, one page at a
    time. Admin only — callers must gate this themselves (see require_admin)."""
    limit = min(max(limit, 1), MAX_PAGE_LIMIT)
    offset = max(offset, 0)
    return await _get({"order": "id.desc", "limit": str(limit), "offset": str(offset)})


async def count_all() -> int:
    """Exact total row count in audit_log, independent of any page/limit — so
    a UI counter can show the true total even once the log outgrows
    MAX_PAGE_LIMIT, without fetching every row to do it.

    Uses PostgREST's `Prefer: count=exact`, which reports the total via the
    `Content-Range` response header even when `limit=0` returns no rows."""
    if not SUPABASE_URL or not SERVICE_KEY:
        log.warning("audit: Supabase not configured; returning zero audit count")
        return 0
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/audit_log",
                headers={
                    "apikey": SERVICE_KEY,
                    "Authorization": f"Bearer {SERVICE_KEY}",
                    "Prefer": "count=exact",
                },
                params={"select": "id", "limit": "0"},
            )
        if response.status_code >= 300:
            log.warning("audit: count failed: %s %s", response.status_code, response.text)
            return 0
        total = response.headers.get("content-range", "").rsplit("/", 1)[-1]
        return int(total) if total.isdigit() else 0
    except Exception as exc:
        log.warning("audit: count error: %s", exc)
        return 0


async def list_recent_for_actor(
    actor_id: str, limit: int = DEFAULT_PAGE_LIMIT, offset: int = 0
) -> list[dict[str, Any]]:
    """Fetch audit_log rows for one actor, newest first, one page at a time.
    Filtered server-side so a caller can only ever see their own rows,
    regardless of what any client sends."""
    limit = min(max(limit, 1), MAX_PAGE_LIMIT)
    offset = max(offset, 0)
    return await _get(
        {"actor_id": f"eq.{actor_id}", "order": "id.desc", "limit": str(limit), "offset": str(offset)}
    )
