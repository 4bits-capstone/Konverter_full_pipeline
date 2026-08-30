from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

_POLL_INTERVAL_SECONDS = 3.0
_TERMINAL_FAILURE_STATUSES = {"FAILED", "CANCELLED", "TIMED_OUT"}


def submit(endpoint_url: str, api_key: str, payload: dict[str, Any]) -> str:
    response = httpx.post(
        f"{endpoint_url.rstrip('/')}/run",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"input": payload},
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["id"])


def poll(
    endpoint_url: str,
    api_key: str,
    job_id: str,
    on_progress: Callable[[], None] | None = None,
) -> dict[str, Any]:
    url = f"{endpoint_url.rstrip('/')}/status/{job_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    while True:
        response = httpx.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        body = response.json()
        status = body.get("status")
        if status == "COMPLETED":
            return body.get("output") or {}
        if status in _TERMINAL_FAILURE_STATUSES:
            raise RuntimeError(
                f"RunPod job {job_id} {status.lower()}: {body.get('error')}"
            )
        if on_progress is not None:
            on_progress()
        time.sleep(_POLL_INTERVAL_SECONDS)
