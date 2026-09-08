from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

TABLE = "wordpress_publications"


async def record_publication(
    *,
    document_id: str,
    page_id: int,
    status: str,
    content_hash: str,
    title: str,
    edit_url: str,
    preview_url: str,
    published_at: str,
    actor_id: str | None,
    actor_email: str | None,
) -> None:
    """Append one durable record of a real WordPress publish call.

    Unlike the per-document local cache (wordpress-publication.json), this
    survives document edits/re-approval and process restarts, so a stale
    local cache can never make the backend forget that a page already
    exists for this document.
    """
    if not SUPABASE_URL or not SERVICE_KEY:
        log.warning(
            "wordpress_registry: Supabase not configured; duplicate-publish "
            "safeguard is disabled for document %s",
            document_id,
        )
        return
    row = {
        "document_id": document_id,
        "page_id": page_id,
        "status": status,
        "content_hash": content_hash,
        "title": title,
        "edit_url": edit_url,
        "preview_url": preview_url,
        "published_at": published_at,
        "actor_id": actor_id,
        "actor_email": actor_email,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{SUPABASE_URL}/rest/v1/{TABLE}",
                headers={
                    "apikey": SERVICE_KEY,
                    "Authorization": f"Bearer {SERVICE_KEY}",
                    "Content-Type": "application/json",
                },
                json=row,
            )
        if response.status_code >= 300:
            log.warning(
                "wordpress_registry: write failed: %s %s",
                response.status_code,
                response.text,
            )
    except Exception as exc:
        log.warning("wordpress_registry: write error: %s", exc)


async def find_latest(document_id: str) -> dict[str, Any] | None:
    """The most recent durable publish record for this document, if any."""
    if not SUPABASE_URL or not SERVICE_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/{TABLE}",
                headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"},
                params={
                    "document_id": f"eq.{document_id}",
                    "order": "published_at.desc",
                    "limit": "1",
                },
            )
        if response.status_code >= 300:
            log.warning(
                "wordpress_registry: lookup failed: %s %s",
                response.status_code,
                response.text,
            )
            return None
        rows = response.json()
        return rows[0] if rows else None
    except Exception as exc:
        log.warning("wordpress_registry: lookup error: %s", exc)
        return None
