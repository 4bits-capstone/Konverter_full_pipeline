from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import Settings
from .models import WordPressPublicationResult


class WordPressPublishingError(RuntimeError):
    """Safe, user-facing WordPress publishing failure."""


class WordPressNotConfiguredError(WordPressPublishingError):
    pass


class WordPressAuthenticationError(WordPressPublishingError):
    pass


class WordPressTimeoutError(WordPressPublishingError):
    pass


_CHECK_BEFORE_RETRY = " Check WordPress Pages before retrying; a page may already exist."


def _created_page_id(payload: Any, status: str = "draft") -> int:
    """Read common REST/plugin response shapes without forwarding raw data.

    Only the request schema has been supplied for Nam Builder. Accept a flat
    page object or a data/page wrapper, with or without a success flag. Never
    treat HTTP 2xx or success=true alone as evidence of a created page.
    """
    page = payload
    for _ in range(3):
        if not isinstance(page, dict):
            break
        if ("success" in page and page["success"] is not True) or page.get("error"):
            raise WordPressPublishingError(
                "WordPress did not confirm that the page was created."
                + _CHECK_BEFORE_RETRY
            )
        if "status" in page and page["status"] not in (status, "success"):
            raise WordPressPublishingError(
                "WordPress returned an unexpected page status."
                + _CHECK_BEFORE_RETRY
            )
        if "data" in page:
            page = page["data"]
        elif "page" in page:
            page = page["page"]
        else:
            page_id = next(
                (page[key] for key in ("page_id", "pageId", "id", "ID", "post_id") if key in page),
                None,
            )
            if isinstance(page_id, str) and page_id.isascii() and page_id.isdecimal() and len(page_id) <= 19:
                page_id = int(page_id)
            if type(page_id) is int and 0 < page_id <= 2**63 - 1:
                return page_id
            break
    raise WordPressPublishingError(
        "WordPress returned an unrecognised page response (missing or invalid page ID)."
        + _CHECK_BEFORE_RETRY
    )


def _draft_links(endpoint_url: str, page_id: int, status: str = "draft") -> tuple[str, str]:
    """Build standard WordPress links from the validated ID, not remote URLs.

    This prevents a plugin response from reflecting credentials, nonces, or
    arbitrary links into the browser, publication cache, or audit log. The
    viewer signs into WordPress normally to view a draft; Konverter does not
    copy that browser session. Also support WordPress in a subdirectory.
    """
    endpoint = urlsplit(endpoint_url)
    prefix = endpoint.path.split("/wp-json/", 1)[0] if "/wp-json/" in endpoint.path else ""
    base = urlunsplit((endpoint.scheme, endpoint.netloc, prefix, "", ""))
    return (
        f"{base}/wp-admin/post.php?post={page_id}&action=edit",
        f"{base}/?page_id={page_id}" + ("&preview=true" if status == "draft" else ""),
    )


class WordPressPublisher:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def _require_configuration(self) -> None:
        if not (
            self.settings.wordpress_publish_url
            and self.settings.wordpress_bearer_token
        ):
            raise WordPressNotConfiguredError(
                "WordPress publishing is not configured on the server. "
                "Set the WordPress endpoint and Bearer token in the backend .env, then restart FastAPI."
            )

    async def publish(
        self,
        *,
        title: str,
        html: str,
        idempotency_key: str,
        status: Literal["draft", "publish"] = "draft",
    ) -> WordPressPublicationResult:
        self._require_configuration()
        if status not in {"draft", "publish"}:
            raise WordPressPublishingError("Choose draft or live publishing.")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.wordpress_bearer_token}",
            "Idempotency-Key": idempotency_key,
            "User-Agent": "Konverter/0.2 WordPressPublisher",
        }
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=self.settings.wordpress_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.settings.wordpress_publish_url,
                    headers=headers,
                    json={
                        "title": title,
                        "html": html,
                        "status": status,
                    },
                )
        except httpx.TimeoutException:
            raise WordPressTimeoutError(
                "WordPress took too long to confirm the page." + _CHECK_BEFORE_RETRY
            ) from None
        except httpx.RequestError:
            raise WordPressPublishingError(
                "The connection to WordPress failed." + _CHECK_BEFORE_RETRY
            ) from None

        if response.status_code in {401, 403}:
            raise WordPressAuthenticationError(
                "WordPress rejected the server Bearer token or its permissions. "
                "Check the backend token with the staging administrator."
            )
        if response.is_redirect:
            raise WordPressPublishingError(
                "WordPress redirected the publishing request unexpectedly. "
                "Check the configured endpoint URL."
            )
        if response.status_code == 404:
            raise WordPressPublishingError(
                "The Nam Builder pages endpoint was not found. "
                "Check its URL and that the staging plugin is enabled."
            )
        if not response.is_success:
            # Do not include the remote response body: plugins sometimes echo
            # request/authentication details in error payloads.
            raise WordPressPublishingError(
                "WordPress could not confirm page creation." + _CHECK_BEFORE_RETRY
            )

        try:
            payload = response.json()
        except ValueError:
            raise WordPressPublishingError(
                "WordPress returned an invalid publishing response." + _CHECK_BEFORE_RETRY
            ) from None
        page_id = _created_page_id(payload, status)
        edit_url, preview_url = _draft_links(self.settings.wordpress_publish_url, page_id, status)
        return WordPressPublicationResult(
            success=True,
            page_id=page_id,
            status=status,
            edit_url=edit_url,
            preview_url=preview_url,
            published_at=datetime.now(timezone.utc).isoformat(),
        )
