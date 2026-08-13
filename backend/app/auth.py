from __future__ import annotations

import os

import httpx
from fastapi import Header, HTTPException

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
