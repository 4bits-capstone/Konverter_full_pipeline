"""Security regression tests: path traversal, upload validation, XSS, limits.

These encode the findings of the August 2026 security review so the
protections cannot silently regress.
"""

from __future__ import annotations

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
