from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import Request


class SlidingWindowLimiter:
    """In-memory sliding-window rate limiter keyed by an arbitrary string.

    The backend runs as a single uvicorn process (KONVERTER_WORKERS=1), so a
    process-local counter is enough; it resets on restart, which is fine for
    abuse protection. A limit of 0 disables the limiter."""

    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        """Record a request for key. Returns None if it's allowed, or the
        number of seconds until the caller may retry if it's over the limit
        (in which case the request is not counted)."""
        if self.limit <= 0:
            return None
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            # Sweep keys whose every hit has aged out, so the dict stays
            # bounded to callers seen within the current window.
            for stale in [k for k, hits in self._hits.items() if hits[-1] <= cutoff]:
                del self._hits[stale]
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1.0, hits[0] + self.window_seconds - now)
            hits.append(now)
            return None


def client_ip(request: Request) -> str:
    """The caller's IP. In production every request arrives through the
    RunPod proxy (Cloudflare), which sets CF-Connecting-IP and overwrites any
    value the client sent; locally there's no proxy, so fall back to the
    socket peer."""
    forwarded = request.headers.get("cf-connecting-ip", "").strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"
