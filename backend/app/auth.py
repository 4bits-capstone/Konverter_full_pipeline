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


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """Return the Supabase user for the request's bearer token, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]

    cached = _token_cache.get(token)
    if cached and cached[0] > time.monotonic():
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


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Reuses get_current_user, then requires app_metadata.role == 'admin'.

    app_metadata is only settable via the Supabase service role / dashboard,
    never by the user themselves, so it's safe to gate on.
    """
    role = (user.get("app_metadata") or {}).get("role")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
