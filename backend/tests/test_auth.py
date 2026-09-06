from __future__ import annotations

import asyncio
import time

import httpx

from app import auth


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, *args, **kwargs) -> _FakeResponse:
        _FakeAsyncClient.calls += 1
        return _FakeResponse(200, {"id": "user-1", "email": "reviewer@example.com"})


def test_validated_token_is_cached_and_not_revalidated_on_every_request(monkeypatch):
    auth._token_cache.clear()
    _FakeAsyncClient.calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    first = asyncio.run(auth.get_current_user(authorization="Bearer test-token"))
    second = asyncio.run(auth.get_current_user(authorization="Bearer test-token"))

    assert first == {"id": "user-1", "email": "reviewer@example.com"}
    assert second == first
    assert _FakeAsyncClient.calls == 1


def test_expired_cache_entry_revalidates_against_supabase(monkeypatch):
    auth._token_cache.clear()
    _FakeAsyncClient.calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    asyncio.run(auth.get_current_user(authorization="Bearer test-token"))
    assert _FakeAsyncClient.calls == 1

    _, user = auth._token_cache["test-token"]
    auth._token_cache["test-token"] = (time.monotonic() - 1, user)

    asyncio.run(auth.get_current_user(authorization="Bearer test-token"))
    assert _FakeAsyncClient.calls == 2


def test_different_tokens_are_cached_independently(monkeypatch):
    auth._token_cache.clear()
    _FakeAsyncClient.calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    asyncio.run(auth.get_current_user(authorization="Bearer token-a"))
    asyncio.run(auth.get_current_user(authorization="Bearer token-b"))

    assert _FakeAsyncClient.calls == 2
    assert set(auth._token_cache.keys()) == {"token-a", "token-b"}


def test_expired_entries_for_other_tokens_are_pruned_not_kept_forever(monkeypatch):
    """An entry used to be deleted only if the exact same token string came
    back around — every distinct token a user ever presented (each access-
    token rotation) otherwise stayed in the cache permanently, an unbounded
    slow leak over a long-running process. A stale, unrelated entry must be
    swept away by ordinary traffic on other tokens, not just its own."""
    auth._token_cache.clear()
    _FakeAsyncClient.calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    asyncio.run(auth.get_current_user(authorization="Bearer old-token"))
    _, user = auth._token_cache["old-token"]
    auth._token_cache["old-token"] = (time.monotonic() - 1, user)

    asyncio.run(auth.get_current_user(authorization="Bearer new-token"))

    assert "old-token" not in auth._token_cache
    assert "new-token" in auth._token_cache
