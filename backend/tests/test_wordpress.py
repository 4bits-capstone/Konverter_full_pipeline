from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import app.main as app_main
from app.config import Settings, load_settings
from app.models import WordPressPublicationResult
from app.wordpress import (
    WordPressAuthenticationError,
    WordPressNotConfiguredError,
    WordPressPublisher,
    WordPressPublishingError,
    WordPressTimeoutError,
)
from test_api import confirm_metadata, load_client, upload_and_process


TEST_TOKEN = "test-only-bearer-token.not-a-real-credential"
ENDPOINT = "https://vlrc.komosion.com/wp-json/nam-builder/v1/pages"


def _configured_settings(monkeypatch) -> Settings:
    monkeypatch.setenv(
        "KONVERTER_WORDPRESS_PUBLISH_URL",
        ENDPOINT,
    )
    monkeypatch.setenv("KONVERTER_WORDPRESS_BEARER_TOKEN", TEST_TOKEN)
    return load_settings()


def test_wordpress_client_keeps_credentials_out_of_payload_and_uses_draft(monkeypatch, caplog):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            201,
            json={
                "success": True,
                "page_id": 26036,
                "edit_url": "https://vlrc.komosion.com/wp-admin/post.php?post=26036&action=edit",
                "preview_url": "https://vlrc.komosion.com/?page_id=26036&preview=true",
            },
        )

    settings = _configured_settings(monkeypatch)
    assert TEST_TOKEN not in repr(settings)
    publisher = WordPressPublisher(
        settings,
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        publisher.publish(
            title="Accessibility Standards Report",
            html="<main>Reviewed report</main>",
            idempotency_key="konverter-test-signature",
        )
    )

    request = captured["request"]
    payload = json.loads(request.content)
    assert payload == {
        "title": "Accessibility Standards Report",
        "html": "<main>Reviewed report</main>",
        "status": "draft",
    }
    assert request.headers["Idempotency-Key"] == "konverter-test-signature"
    assert request.method == "POST"
    assert str(request.url) == ENDPOINT
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Authorization"] == f"Bearer {TEST_TOKEN}"
    assert "Cookie" not in request.headers
    assert "X-NB-Nonce" not in request.headers
    assert TEST_TOKEN not in str(request.url)
    assert TEST_TOKEN not in request.content.decode()
    assert TEST_TOKEN not in result.model_dump_json()
    assert TEST_TOKEN not in caplog.text
    assert result.page_id == 26036
    assert result.status == "draft"


def test_wordpress_config_rejects_plain_http_for_remote_hosts(monkeypatch):
    monkeypatch.setenv(
        "KONVERTER_WORDPRESS_PUBLISH_URL",
        "http://vlrc.komosion.com/wp-json/nam-builder/v1/pages",
    )
    with pytest.raises(ValueError, match="must use HTTPS"):
        load_settings()


@pytest.mark.parametrize("remote_url", [
    "https://malicious.example/redirect",
    "javascript:alert(1)",
    f"https://vlrc.komosion.com/?access_token={TEST_TOKEN}&preview_nonce=private",
    "https://vlrc.komosion.com\\@malicious.example/",
])
def test_wordpress_client_never_forwards_remote_links_or_secrets(monkeypatch, remote_url):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "page_id": 26036,
                "preview_url": remote_url,
                "edit_url": remote_url,
                "token": TEST_TOKEN,
            },
        )

    publisher = WordPressPublisher(
        _configured_settings(monkeypatch),
        transport=httpx.MockTransport(handler),
    )
    result = _publish(publisher)
    assert result.preview_url == "https://vlrc.komosion.com/?page_id=26036&preview=true"
    assert result.edit_url == "https://vlrc.komosion.com/wp-admin/post.php?post=26036&action=edit"
    assert TEST_TOKEN not in result.model_dump_json()
    assert "nonce" not in result.model_dump_json()


def _publish(publisher):
    return asyncio.run(publisher.publish(
        title="Report", html="<main>Report</main>", idempotency_key="konverter-test-signature",
    ))


@pytest.mark.parametrize("response", [
    {"id": 26036, "status": "draft"},
    {"page_id": 26036},
    {"pageId": 26036},
    {"post_id": 26036},
    {"ID": 26036},
    {"id": "26036"},
    {"success": True, "data": {"id": 26036, "status": "draft"}},
    {"data": {"page_id": 26036}},
    {"page": {"id": 26036}},
    {"success": True, "data": {"page": {"id": 26036}}},
])
def test_wordpress_supported_response_shapes(monkeypatch, response):
    publisher = WordPressPublisher(_configured_settings(monkeypatch), transport=httpx.MockTransport(
        lambda request: httpx.Response(201, json=response),
    ))
    assert _publish(publisher).page_id == 26036


@pytest.mark.parametrize("response", [
    {}, None, [], "created", {"success": True}, {"id": True}, {"id": False},
    {"id": 0}, {"id": -1}, {"id": 1.5}, {"id": "26036?token=private"},
    {"id": "٢٦٠٣٦"}, {"id": 2**64}, {"id": "9" * 100}, {"id": []},
    {"success": False, "id": 26036}, {"success": "true", "id": 26036},
    {"error": TEST_TOKEN, "id": 26036}, {"id": 26036, "status": "publish"},
    {"id": 26036, "status": []}, {"success": True, "data": []},
    {"data": {"success": False, "id": 26036}},
    {"data": {"id": 26036, "status": "publish"}},
])
def test_wordpress_unconfirmed_response_does_not_claim_success(monkeypatch, response):
    publisher = WordPressPublisher(_configured_settings(monkeypatch), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response),
    ))
    with pytest.raises(WordPressPublishingError) as exc:
        _publish(publisher)
    assert "Check WordPress Pages before retrying" in str(exc.value)
    assert TEST_TOKEN not in str(exc.value)


@pytest.mark.parametrize("token", ["Bearer test-secret", "test\r\nsecret", "test secret", "秘密", "x" * 8193])
def test_wordpress_config_rejects_malformed_tokens_without_echoing_them(monkeypatch, token):
    monkeypatch.setenv("KONVERTER_WORDPRESS_BEARER_TOKEN", token)
    with pytest.raises(ValueError) as exc:
        load_settings()
    assert token not in str(exc.value)


@pytest.mark.parametrize("missing", ["KONVERTER_WORDPRESS_PUBLISH_URL", "KONVERTER_WORDPRESS_BEARER_TOKEN"])
def test_wordpress_requires_backend_configuration_before_network(monkeypatch, missing):
    _configured_settings(monkeypatch)
    monkeypatch.delenv(missing)
    def unexpected_request(request):
        pytest.fail("No network request should happen without configuration")
    publisher = WordPressPublisher(load_settings(), transport=httpx.MockTransport(unexpected_request))
    with pytest.raises(WordPressNotConfiguredError):
        _publish(publisher)


def test_wordpress_legacy_credentials_cannot_replace_bearer_token(monkeypatch):
    _configured_settings(monkeypatch)
    monkeypatch.delenv("KONVERTER_WORDPRESS_BEARER_TOKEN")
    monkeypatch.setenv("KONVERTER_WORDPRESS_USERNAME", "old-user")
    monkeypatch.setenv("KONVERTER_WORDPRESS_APPLICATION_PASSWORD", "old-password")
    with pytest.raises(WordPressNotConfiguredError):
        _publish(WordPressPublisher(load_settings()))


@pytest.mark.parametrize("status_code", [301, 302, 307, 308, 400, 401, 403, 404, 413, 429, 500])
def test_wordpress_errors_never_forward_secrets_or_follow_redirects(monkeypatch, status_code, caplog):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status_code, headers={"Location": "https://malicious.example"},
                             json={"message": TEST_TOKEN, "Authorization": f"Bearer {TEST_TOKEN}"})
    publisher = WordPressPublisher(_configured_settings(monkeypatch), transport=httpx.MockTransport(handler))
    with pytest.raises(WordPressPublishingError) as exc:
        _publish(publisher)
    assert len(calls) == 1
    assert TEST_TOKEN not in str(exc.value)
    assert TEST_TOKEN not in caplog.text
    if status_code in {401, 403}:
        assert isinstance(exc.value, WordPressAuthenticationError)


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError, httpx.WriteError])
def test_wordpress_transport_errors_are_safe_and_never_retried(monkeypatch, error_type):
    calls = []
    def handler(request):
        calls.append(request)
        raise error_type(TEST_TOKEN, request=request)
    publisher = WordPressPublisher(_configured_settings(monkeypatch), transport=httpx.MockTransport(handler))
    with pytest.raises(WordPressPublishingError) as exc:
        _publish(publisher)
    assert len(calls) == 1
    assert TEST_TOKEN not in str(exc.value)
    assert exc.value.__suppress_context__ is True
    assert "Check WordPress Pages before retrying" in str(exc.value)
    if error_type is httpx.ReadTimeout:
        assert isinstance(exc.value, WordPressTimeoutError)


def test_wordpress_non_json_success_is_safe(monkeypatch):
    publisher = WordPressPublisher(_configured_settings(monkeypatch), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=f"<html>{TEST_TOKEN}</html>"),
    ))
    with pytest.raises(WordPressPublishingError) as exc:
        _publish(publisher)
    assert TEST_TOKEN not in str(exc.value)
    assert exc.value.__suppress_context__ is True


def test_wordpress_links_support_subdirectory_install(monkeypatch):
    _configured_settings(monkeypatch)
    monkeypatch.setenv("KONVERTER_WORDPRESS_PUBLISH_URL", "https://vlrc.komosion.com/staging/wp-json/nam-builder/v1/pages")
    publisher = WordPressPublisher(load_settings(), transport=httpx.MockTransport(
        lambda request: httpx.Response(201, json={"id": 26036}),
    ))
    result = _publish(publisher)
    assert result.preview_url == "https://vlrc.komosion.com/staging/?page_id=26036&preview=true"
    assert result.edit_url == "https://vlrc.komosion.com/staging/wp-admin/post.php?post=26036&action=edit"


class _FakeWordPressPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def publish(self, *, title: str, html: str, idempotency_key: str):
        self.calls.append(
            {"title": title, "html": html, "idempotency_key": idempotency_key}
        )
        return WordPressPublicationResult(
            success=True,
            page_id=26036,
            status="draft",
            edit_url="https://vlrc.komosion.com/wp-admin/post.php?post=26036&action=edit",
            preview_url="https://vlrc.komosion.com/?page_id=26036&preview=true",
            published_at="2026-09-06T10:00:00+00:00",
        )


def _approved_document(client) -> str:
    document_id = upload_and_process(client)
    assert client.post(
        f"/api/documents/{document_id}/review-items/resolve-all"
    ).status_code == 200
    confirm_metadata(client, document_id)
    assert client.post(f"/api/documents/{document_id}/approval").status_code == 200
    return document_id


def test_publish_endpoint_is_authenticated_persistent_and_idempotent(tmp_path, monkeypatch):
    with load_client(tmp_path) as client:
        document_id = _approved_document(client)
        fake = _FakeWordPressPublisher()
        monkeypatch.setattr(app_main, "wordpress", fake)

        first = client.post(f"/api/documents/{document_id}/wordpress-publication")
        assert first.status_code == 200
        assert first.json()["pageId"] == 26036
        assert first.json()["status"] == "draft"
        assert len(fake.calls) == 1
        assert fake.calls[0]["title"] == "Accessibility Standards Report"
        assert "Accessibility Standards Report" in fake.calls[0]["html"]

        status = client.get(f"/api/documents/{document_id}/wordpress-publication")
        assert status.status_code == 200
        assert status.json() == first.json()

        retry = client.post(f"/api/documents/{document_id}/wordpress-publication")
        assert retry.status_code == 200
        assert retry.json() == first.json()
        assert len(fake.calls) == 1

        cached = app_main.store.read_artifact(
            document_id, app_main.WORDPRESS_PUBLICATION_ARTIFACT
        )
        serialised = json.dumps(cached)
        assert "application-password" not in serialised
        assert "Authorization" not in serialised
        assert "nonce" not in serialised.lower()


def test_publish_endpoint_requires_approval_and_owner(tmp_path, monkeypatch):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        fake = _FakeWordPressPublisher()
        monkeypatch.setattr(app_main, "wordpress", fake)

        unapproved = client.post(
            f"/api/documents/{document_id}/wordpress-publication"
        )
        assert unapproved.status_code == 409
        assert fake.calls == []

        client.app.dependency_overrides[app_main.get_current_user] = lambda: {
            "id": "another-user",
            "email": "another@example.test",
        }
        hidden = client.post(f"/api/documents/{document_id}/wordpress-publication")
        assert hidden.status_code == 404
        assert fake.calls == []


def test_publish_endpoint_rejects_a_missing_session(tmp_path):
    with load_client(tmp_path) as client:
        document_id = _approved_document(client)
        client.app.dependency_overrides.pop(app_main.get_current_user, None)
        response = client.post(
            f"/api/documents/{document_id}/wordpress-publication"
        )
        assert response.status_code == 401


def test_bearer_api_through_fastapi_returns_and_caches_only_safe_metadata(tmp_path, monkeypatch):
    with load_client(tmp_path) as client:
        document_id = _approved_document(client)
        calls = []
        def handler(request):
            calls.append(request)
            assert request.headers["Authorization"] == f"Bearer {TEST_TOKEN}"
            assert set(json.loads(request.content)) == {"title", "html", "status"}
            return httpx.Response(201, json={
                "success": True,
                "data": {"id": 26036, "status": "draft", "token": TEST_TOKEN,
                         "preview_url": f"https://vlrc.komosion.com/?token={TEST_TOKEN}"},
            })
        settings = _configured_settings(monkeypatch)
        monkeypatch.setattr(app_main, "settings", settings)
        monkeypatch.setattr(app_main, "wordpress", WordPressPublisher(settings, transport=httpx.MockTransport(handler)))
        path = f"/api/documents/{document_id}/wordpress-publication"
        first = client.post(path)
        assert first.status_code == 200
        assert first.json()["pageId"] == 26036
        assert first.json()["previewUrl"] == "https://vlrc.komosion.com/?page_id=26036&preview=true"
        assert TEST_TOKEN not in first.text
        assert client.post(path).json() == first.json()
        assert client.get(path).json() == first.json()
        assert len(calls) == 1
        cached = app_main.store.read_artifact(document_id, app_main.WORDPRESS_PUBLICATION_ARTIFACT)
        assert TEST_TOKEN not in json.dumps(cached)
        assert "Authorization" not in json.dumps(cached)


@pytest.mark.parametrize("wp_status, api_status", [(401, 502), (403, 502), (404, 502), (500, 502), (200, 502)])
def test_bearer_endpoint_failure_is_safe_and_not_cached(tmp_path, monkeypatch, wp_status, api_status):
    with load_client(tmp_path) as client:
        document_id = _approved_document(client)
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(wp_status, json={"message": TEST_TOKEN})
        monkeypatch.setattr(app_main, "wordpress", WordPressPublisher(
            _configured_settings(monkeypatch), transport=httpx.MockTransport(handler),
        ))
        path = f"/api/documents/{document_id}/wordpress-publication"
        result = client.post(path)
        assert result.status_code == api_status
        assert TEST_TOKEN not in result.text
        assert len(calls) == 1
        assert client.get(path).json() is None


def test_wordpress_cache_is_scoped_to_target_endpoint(monkeypatch):
    record = {"id": "test-document", "approved_at": "test-approval"}
    monkeypatch.setattr(app_main, "settings", _configured_settings(monkeypatch))
    first = app_main._wordpress_source_signature(record, "<main>Report</main>")
    monkeypatch.setenv("KONVERTER_WORDPRESS_PUBLISH_URL", "https://other.example/wp-json/nam-builder/v1/pages")
    monkeypatch.setattr(app_main, "settings", load_settings())
    second = app_main._wordpress_source_signature(record, "<main>Report</main>")
    assert first != second
