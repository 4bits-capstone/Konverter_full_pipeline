from __future__ import annotations

import httpx
import pytest

from app import runpod_client

ENDPOINT = "https://api.runpod.ai/v2/endpoint-id"


class FakeRunPod:
    """Replays a scripted list of status-check outcomes and records cancels."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.status_calls = 0
        self.cancelled: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.status_calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        request = httpx.Request("GET", url)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, int):
            return httpx.Response(outcome, request=request)
        return httpx.Response(200, json=outcome, request=request)

    def post(self, url, headers=None, timeout=None, json=None):
        self.cancelled.append(url.rsplit("/", 1)[-1])
        return httpx.Response(200, json={}, request=httpx.Request("POST", url))


@pytest.fixture
def clock(monkeypatch):
    """Fake monotonic clock that advances only when the client sleeps."""
    now = {"t": 0.0}
    monkeypatch.setattr(runpod_client.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(
        runpod_client.time, "sleep", lambda seconds: now.__setitem__("t", now["t"] + seconds)
    )
    return now


def install(monkeypatch, fake):
    monkeypatch.setattr(runpod_client.httpx, "get", fake.get)
    monkeypatch.setattr(runpod_client.httpx, "post", fake.post)


def test_poll_returns_output_when_job_completes(monkeypatch, clock):
    fake = FakeRunPod([
        {"status": "IN_QUEUE"},
        {"status": "IN_PROGRESS"},
        {"status": "COMPLETED", "output": {"ok": True}},
    ])
    install(monkeypatch, fake)

    assert runpod_client.poll(ENDPOINT, "key", "job-1") == {"ok": True}
    assert fake.cancelled == []


def test_poll_times_out_and_cancels_stuck_job(monkeypatch, clock):
    fake = FakeRunPod([{"status": "IN_PROGRESS"}])
    install(monkeypatch, fake)

    with pytest.raises(runpod_client.RunPodJobTimeoutError):
        runpod_client.poll(ENDPOINT, "key", "job-1", timeout_seconds=60)

    assert fake.cancelled == ["job-1"]
    assert clock["t"] >= 60


def test_poll_retries_transient_errors(monkeypatch, clock):
    fake = FakeRunPod([
        httpx.ConnectError("connection reset"),
        503,
        429,
        {"status": "COMPLETED", "output": {"ok": True}},
    ])
    install(monkeypatch, fake)

    assert runpod_client.poll(ENDPOINT, "key", "job-1") == {"ok": True}
    assert fake.status_calls == 4
    assert fake.cancelled == []


def test_poll_gives_up_after_too_many_consecutive_transient_errors(monkeypatch, clock):
    fake = FakeRunPod([503])
    install(monkeypatch, fake)

    with pytest.raises(httpx.HTTPStatusError):
        runpod_client.poll(ENDPOINT, "key", "job-1")

    assert fake.status_calls == runpod_client._MAX_CONSECUTIVE_TRANSIENT_ERRORS + 1
    assert fake.cancelled == ["job-1"]


def test_poll_fails_fast_on_non_transient_error(monkeypatch, clock):
    fake = FakeRunPod([401])
    install(monkeypatch, fake)

    with pytest.raises(httpx.HTTPStatusError):
        runpod_client.poll(ENDPOINT, "key", "job-1")

    assert fake.status_calls == 1
    assert fake.cancelled == ["job-1"]


def test_poll_raises_when_job_fails(monkeypatch, clock):
    fake = FakeRunPod([{"status": "FAILED", "error": "CUDA out of memory"}])
    install(monkeypatch, fake)

    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        runpod_client.poll(ENDPOINT, "key", "job-1")


def test_poll_cancels_job_when_caller_stops_processing(monkeypatch, clock):
    fake = FakeRunPod([{"status": "IN_PROGRESS"}])
    install(monkeypatch, fake)

    def stop():
        raise InterruptedError

    with pytest.raises(InterruptedError):
        runpod_client.poll(ENDPOINT, "key", "job-1", on_progress=stop)

    assert fake.cancelled == ["job-1"]
