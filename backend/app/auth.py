from __future__ import annotations

import os
import time

import httpx
from fastapi import Depends, Header, HTTPException

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

# The frontend polls several endpoints in parallel (job status, review
# items, document list), so a single page can fire a burst of concurrent
# requests that each independently re-validate the same bearer token
# against Supabase. Caching a validated token briefly cuts that redundant
# traffic, which was the source of occasional transient 401s on a token
# that was valid a moment earlier.
_TOKEN_CACHE_TTL_SECONDS = 5.0
_token_cache: dict[str, tuple[float, dict]] = {}


def _prune_expired_tokens(now: float) -> None:
    # Each distinct bearer token a user ever presents (every Supabase
    # access-token rotation, roughly hourly per active session) becomes a
    # permanent dict key otherwise — an entry is only ever overwritten if
    # the exact same token string comes back, never deleted once its TTL
    # passes. Sweeping expired entries on every call keeps the cache
    # bounded to whatever's actually been looked up in the last few
    # seconds, since the TTL itself is short.
    expired = [key for key, (expiry, _) in _token_cache.items() if expiry <= now]
    for key in expired:
        del _token_cache[key]


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """Return the Supabase user for the request's bearer token, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]

    now = time.monotonic()
    _prune_expired_tokens(now)
    cached = _token_cache.get(token)
    if cached and cached[0] > now:
        return cached[1]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = resp.json()  # includes the user's id and email
    _token_cache[token] = (time.monotonic() + _TOKEN_CACHE_TTL_SECONDS, user)
    return user


async def get_current_user_optional(
    authorization: str | None = Header(default=None),
) -> dict | None:
    """Like get_current_user, but returns None instead of 401 when no bearer
    token is presented at all — for endpoints that serve a resource publicly
    once it reaches some state (e.g. approved-for-publication) but must
    still enforce ownership before that. An invalid/expired token is still
    a hard 401, since presenting *a* token implies the caller expects it to
    be honoured, not silently downgraded to anonymous."""
    if not authorization:
        return None
    return await get_current_user(authorization)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Reuses get_current_user, then requires app_metadata.role == 'admin'.

    app_metadata is only settable via the Supabase service role / dashboard,
    never by the user themselves, so it's safe to gate on.
    """
    role = (user.get("app_metadata") or {}).get("role")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
