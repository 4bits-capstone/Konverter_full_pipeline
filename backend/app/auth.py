from __future__ import annotations

import os

import httpx
from fastapi import Depends, Header, HTTPException

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """Return the Supabase user for the request's bearer token, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return resp.json()  # includes the user's id and email


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Reuses get_current_user, then requires app_metadata.role == 'admin'.

    app_metadata is only settable via the Supabase service role / dashboard,
    never by the user themselves, so it's safe to gate on.
    """
    role = (user.get("app_metadata") or {}).get("role")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
