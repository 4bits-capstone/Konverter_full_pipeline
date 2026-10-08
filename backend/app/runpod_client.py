from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 3.0
_MAX_CONSECUTIVE_TRANSIENT_ERRORS = 5
_DEFAULT_JOB_TIMEOUT_SECONDS = 1800.0
_TERMINAL_FAILURE_STATUSES = {"FAILED", "CANCELLED", "TIMED_OUT"}


class RunPodJobTimeoutError(RuntimeError):
    pass


def submit(endpoint_url: str, api_key: str, payload: dict[str, Any]) -> str:
    response = httpx.post(
        f"{endpoint_url.rstrip('/')}/run",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"input": payload},
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["id"])


def cancel(endpoint_url: str, api_key: str, job_id: str) -> None:
    """Best-effort cancel so an abandoned job stops consuming GPU time."""
    try:
        httpx.post(
            f"{endpoint_url.rstrip('/')}/cancel/{job_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        log.warning("RunPod cancel for job %s failed: %s", job_id, exc)


def _is_transient(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


def poll(
    endpoint_url: str,
    api_key: str,
    job_id: str,
    on_progress: Callable[[], None] | None = None,
    timeout_seconds: float = _DEFAULT_JOB_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = f"{endpoint_url.rstrip('/')}/status/{job_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.monotonic() + timeout_seconds
    transient_errors = 0
    while True:
        try:
            response = httpx.get(url, headers=headers, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            transient_errors += 1
            if not _is_transient(exc) or transient_errors > _MAX_CONSECUTIVE_TRANSIENT_ERRORS:
                cancel(endpoint_url, api_key, job_id)
                raise
            log.warning(
                "RunPod status check for job %s failed (%d/%d), retrying: %s",
                job_id,
                transient_errors,
                _MAX_CONSECUTIVE_TRANSIENT_ERRORS,
                exc,
            )
        else:
            transient_errors = 0
            body = response.json()
            status = body.get("status")
            if status == "COMPLETED":
                return body.get("output") or {}
            if status in _TERMINAL_FAILURE_STATUSES:
                raise RuntimeError(
                    f"RunPod job {job_id} {status.lower()}: {body.get('error')}"
                )
        if time.monotonic() >= deadline:
            cancel(endpoint_url, api_key, job_id)
            raise RunPodJobTimeoutError(
                f"RunPod job {job_id} did not finish within {timeout_seconds:.0f}s"
            )
        if on_progress is not None:
            try:
                on_progress()
            except BaseException:
                # The caller is abandoning the job (e.g. the user stopped processing).
                cancel(endpoint_url, api_key, job_id)
                raise
        time.sleep(_POLL_INTERVAL_SECONDS)
