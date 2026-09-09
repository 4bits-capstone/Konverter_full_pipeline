from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

TABLE = "wordpress_publications"


class RegistryUnavailableError(Exception):
    """Raised when find_latest could not reach Supabase or got a non-2xx
    response — distinct from a confirmed "no prior publish" result, so the
    caller never mistakes "couldn't check" for "checked, nothing found" and
    silently reopens the duplicate-publish race this registry exists to
    close."""


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
) -> bool:
    """Append one durable record of a real WordPress publish call. Returns
    whether the write actually succeeded, since the caller has already
    created a real WordPress page by the time this runs — a failed write
    here means that page now has zero durable record anywhere, which is a
    genuine data-durability problem worth the caller knowing about, not
    just a line in a log file.

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
        return False
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
            log.error(
                "wordpress_registry: durable write failed for document %s "
                "(WordPress page %s already exists and is now unrecorded): %s %s",
                document_id,
                page_id,
                response.status_code,
                response.text,
            )
            return False
    except Exception as exc:
        log.error(
            "wordpress_registry: durable write error for document %s "
            "(WordPress page %s already exists and is now unrecorded): %s",
            document_id,
            page_id,
            exc,
        )
        return False
    return True


async def find_latest(document_id: str) -> dict[str, Any] | None:
    """The most recent durable publish record for this document, or None
    if none exists. Supabase being unconfigured is a deliberately supported
    mode — the duplicate-publish safeguard is simply disabled, same as
    before — and still returns None. But once Supabase *is* configured, an
    actual lookup failure (network error, timeout, non-2xx response) raises
    RegistryUnavailableError rather than returning None, so the caller can
    never mistake "the lookup itself failed" for "confirmed no prior
    publish" and silently publish an undetected duplicate over what would
    otherwise be a transient hiccup."""
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
            raise RegistryUnavailableError(
                f"lookup failed: {response.status_code} {response.text}"
            )
        rows = response.json()
        return rows[0] if rows else None
    except RegistryUnavailableError:
        raise
    except Exception as exc:
        raise RegistryUnavailableError(f"lookup error: {exc}") from exc
