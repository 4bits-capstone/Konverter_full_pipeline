"""Security regression tests: path traversal, upload validation, XSS, limits.

These encode the findings of the August 2026 security review so the
protections cannot silently regress.
"""

from __future__ import annotations

import app.main as app_main
from test_api import confirm_metadata, load_client, make_pdf, upload_and_process


def test_path_traversal_in_document_id_is_rejected(tmp_path):
    with load_client(tmp_path) as client:
        for candidate in (
            "..%2f..%2fetc%2fpasswd",
            "..%5c..%5cwindows",
            "%2e%2e%2f%2e%2e%2fsecret",
            "a/../../b",
        ):
            response = client.get(f"/api/documents/{candidate}")
            assert response.status_code in {404, 422}, candidate


def test_path_traversal_in_figure_and_evidence_names_is_rejected(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        # Figure keys only allow [a-z0-9-]; anything else must 404.
        for key in ("..%2frecord", "source", "..%5csource", "A%2e%2e"):
            response = client.get(f"/api/documents/{document_id}/figures/{key}.png")
            assert response.status_code == 404, key
        # Evidence item ids are sanitised before touching the filesystem.
        response = client.get(
            f"/api/documents/{document_id}/review-items/..%2f..%2frecord/evidence.png"
        )
        assert response.status_code == 404


def test_non_pdf_uploads_are_rejected(tmp_path):
    with load_client(tmp_path) as client:
        # Wrong extension.
        response = client.post(
            "/api/documents",
            files={"files": ("payload.exe", b"MZ\x90\x00", "application/pdf")},
        )
        assert response.status_code == 415

        # Right extension, wrong content (no %PDF- header in first 1024 bytes).
        response = client.post(
            "/api/documents",
            files={"files": ("fake.pdf", b"<html>not a pdf</html>" * 60, "application/pdf")},
        )
        assert response.status_code == 415

        # Header present but the body is not parseable as a PDF.
        response = client.post(
            "/api/documents",
            files={"files": ("broken.pdf", b"%PDF-1.7 garbage", "application/pdf")},
        )
        assert response.status_code == 422


def test_pdf_with_leading_junk_before_header_is_accepted(tmp_path):
    """The PDF spec allows the %PDF- marker anywhere in the first 1024 bytes."""
    with load_client(tmp_path) as client:
        body = b"\xef\xbb\xbf% preamble junk\n" + make_pdf()
        response = client.post(
            "/api/documents",
            files={"files": ("preamble.pdf", body, "application/pdf")},
        )
        assert response.status_code == 201


def test_traversal_in_uploaded_filename_is_neutralised(tmp_path):
    with load_client(tmp_path) as client:
        response = client.post(
            "/api/documents",
            files={"files": ("../../evil.pdf", make_pdf(), "application/pdf")},
        )
        assert response.status_code == 201
        assert response.json()[0]["fileName"] == "evil.pdf"


def test_metadata_xss_payload_is_escaped_in_generated_html(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        metadata = confirm_metadata(client, document_id)
        metadata["title"] = '<script>alert("xss")</script>'
        metadata["jurisdiction"] = '"><img src=x onerror=alert(1)>'
        assert (
            client.put(
                f"/api/documents/{document_id}/metadata", json=metadata
            ).status_code
            == 200
        )
        assert client.post(f"/api/documents/{document_id}/approval").status_code == 200

        html_response = client.get(
            f"/api/documents/{document_id}/exports/accessible.html"
        )
        assert html_response.status_code == 200
        body = html_response.content
        assert b'<script>alert("xss")</script>' not in body
        assert b"onerror=alert(1)>" not in body
        # The JSON-LD block must stay inert even with a </script> in a value.
        assert b"\\u003c" in body or b"<\\/" in body


def test_oversized_review_patch_is_rejected(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        review = client.get(f"/api/documents/{document_id}/review-items").json()
        response = client.patch(
            f"/api/documents/{document_id}/review-items/{review[0]['id']}",
            json={"correctedText": "x" * 300_000},
        )
        assert response.status_code == 422


def test_security_headers_are_present(tmp_path):
    with load_client(tmp_path) as client:
        response = client.get("/api/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"


def test_exports_require_approval(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        for suffix in ("accessible.html", "schema.jsonld", "structured.json"):
            response = client.get(f"/api/documents/{document_id}/exports/{suffix}")
            assert response.status_code == 409, suffix


def test_action_endpoints_reject_missing_token(tmp_path):
    with load_client(tmp_path) as client:
        # The fixture overrides auth for every other test; drop it here to
        # exercise the real dependency.
        client.app.dependency_overrides.pop(app_main.get_current_user, None)

        response = client.post(
            "/api/documents",
            files={"files": ("report.pdf", make_pdf(), "application/pdf")},
        )
        assert response.status_code == 401


def test_audit_log_rejects_non_admin(tmp_path):
    with load_client(tmp_path) as client:
        # The fixture's fake user has no app_metadata.role at all.
        response = client.get("/api/audit-log")
        assert response.status_code == 403


def test_my_audit_log_allows_any_authenticated_user(tmp_path):
    with load_client(tmp_path) as client:
        # Same non-admin fixture user as above — /mine must still work for them.
        response = client.get("/api/audit-log/mine")
        assert response.status_code == 200
        assert response.json() == []


def test_my_audit_log_rejects_missing_token(tmp_path):
    with load_client(tmp_path) as client:
        client.app.dependency_overrides.pop(app_main.get_current_user, None)
        response = client.get("/api/audit-log/mine")
        assert response.status_code == 401


def test_audit_log_allows_admin(tmp_path):
    with load_client(tmp_path) as client:
        client.app.dependency_overrides[app_main.get_current_user] = lambda: {
            "id": "admin-user",
            "email": "admin@example.test",
            "app_metadata": {"role": "admin"},
        }
        response = client.get("/api/audit-log")
        assert response.status_code == 200
        assert response.json() == []


def test_audit_log_count_rejects_non_admin(tmp_path):
    with load_client(tmp_path) as client:
        response = client.get("/api/audit-log/count")
        assert response.status_code == 403


def test_audit_log_count_allows_admin(tmp_path):
    with load_client(tmp_path) as client:
        client.app.dependency_overrides[app_main.get_current_user] = lambda: {
            "id": "admin-user",
            "email": "admin@example.test",
            "app_metadata": {"role": "admin"},
        }
        response = client.get("/api/audit-log/count")
        assert response.status_code == 200
        # Supabase isn't configured in tests, so count_all() short-circuits to 0.
        assert response.json() == {"total": 0}


def _override_user(client, user_id: str, email: str) -> None:
    client.app.dependency_overrides[app_main.get_current_user] = lambda: {
        "id": user_id,
        "email": email,
    }


def test_documents_are_scoped_to_their_uploader(tmp_path):
    with load_client(tmp_path) as client:
        # Fixture's default fake user ("test-user") uploads a document.
        response = client.post(
            "/api/documents",
            files={"files": ("owned.pdf", make_pdf(), "application/pdf")},
        )
        document_id = response.json()[0]["id"]

        # A different user can't see it in their list...
        _override_user(client, "other-user", "other@example.test")
        listing = client.get("/api/documents").json()
        assert document_id not in [document["id"] for document in listing]

        # ...and can't act on it either — 404, not 403, so its existence
        # isn't confirmed to a non-owner.
        assert client.post(f"/api/documents/{document_id}/process").status_code == 404
        assert client.delete(f"/api/documents/{document_id}").status_code == 404

        # The original owner still sees and can act on their own document.
        _override_user(client, "test-user", "test-user@example.test")
        listing = client.get("/api/documents").json()
        assert document_id in [document["id"] for document in listing]
        assert client.post(f"/api/documents/{document_id}/process").status_code == 200


def test_admins_personal_workflow_is_scoped_like_anyone_elses(tmp_path):
    with load_client(tmp_path) as client:
        response = client.post(
            "/api/documents",
            files={"files": ("owned.pdf", make_pdf(), "application/pdf")},
        )
        document_id = response.json()[0]["id"]

        client.app.dependency_overrides[app_main.get_current_user] = lambda: {
            "id": "admin-user",
            "email": "admin@example.test",
            "app_metadata": {"role": "admin"},
        }

        # The admin's own upload/review workflow behaves like anyone else's —
        # someone else's document doesn't clutter their personal queue...
        assert document_id not in [document["id"] for document in client.get("/api/documents").json()]
        # ...but full oversight is still available via the dedicated admin page...
        all_documents = client.get("/api/documents/all").json()
        assert document_id in [document["id"] for document in all_documents]
        # ...and admin can still act on it despite not owning it (e.g. support/moderation).
        assert client.post(f"/api/documents/{document_id}/process").status_code == 200


def test_documents_all_rejects_non_admin(tmp_path):
    with load_client(tmp_path) as client:
        response = client.get("/api/documents/all")
        assert response.status_code == 403


def test_unapproved_document_read_endpoints_are_scoped_to_their_uploader(tmp_path):
    """The mutating endpoints (process/delete) were already scoped to their
    uploader — see test_documents_are_scoped_to_their_uploader above — but
    the read endpoints a reviewer actually spends their time on
    (get_document, review-items, metadata, publication, processing-summary,
    the raw docling.json export, review/metadata evidence images) had no
    such check at all: a document's own detail page was fully public to
    anyone with its id, with no owner/auth check whatsoever, even though
    the very same id is already correctly hidden from a non-owner's list
    view. Confirmed missing during a pre-production security sweep."""
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        confirm_metadata(client, document_id)
        evidence_item_id = client.get(
            f"/api/documents/{document_id}/review-items"
        ).json()[0]["id"]

        _override_user(client, "other-user", "other@example.test")
        assert client.get(f"/api/documents/{document_id}").status_code == 404
        assert (
            client.get(f"/api/documents/{document_id}/processing-summary").status_code
            == 404
        )
        assert (
            client.get(f"/api/documents/{document_id}/review-items").status_code == 404
        )
        assert client.get(f"/api/documents/{document_id}/metadata").status_code == 404
        assert (
            client.get(f"/api/documents/{document_id}/publication").status_code == 404
        )
        assert (
            client.get(f"/api/documents/{document_id}/exports/docling.json").status_code
            == 404
        )
        assert (
            client.get(
                f"/api/documents/{document_id}/review-items/{evidence_item_id}/evidence.png"
            ).status_code
            == 404
        )
        # /source has its own distinct pre/post-approval auth rules, covered
        # separately by test_source_pdf_requires_auth_before_approval_but_is_public_once_approved.

        # The original owner can still read everything about their own document.
        _override_user(client, "test-user", "test-user@example.test")
        assert client.get(f"/api/documents/{document_id}").status_code == 200
        assert client.get(f"/api/documents/{document_id}/review-items").status_code == 200


def test_source_pdf_requires_auth_before_approval_but_is_public_once_approved(tmp_path):
    """The published, approved export embeds /source as a public "view
    original source" citation link with no Supabase session — so unlike
    every other read endpoint, /source must switch from owner-only to
    fully public the moment the document is approved, not stay gated."""
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)

        # No Authorization header at all (not even the test fixture's
        # mocked user — OptionalUser reads the real header, so this
        # exercises the actual dependency, not the test override).
        client.app.dependency_overrides.pop(app_main.get_current_user, None)
        response = client.get(f"/api/documents/{document_id}/source")
        assert response.status_code == 401
        _override_user(client, "test-user", "test-user@example.test")

        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        confirm_metadata(client, document_id)
        assert client.post(f"/api/documents/{document_id}/approval").status_code == 200

        client.app.dependency_overrides.pop(app_main.get_current_user, None)
        response = client.get(f"/api/documents/{document_id}/source")
        assert response.status_code == 200
