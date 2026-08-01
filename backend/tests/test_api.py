from __future__ import annotations

import importlib
import os
import time
from io import BytesIO

from pypdf import PdfWriter


def make_pdf(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def load_client(tmp_path):
    os.environ["KONVERTER_DATA_DIR"] = str(tmp_path / "runtime")
    os.environ["KONVERTER_WORKERS"] = "1"
    os.environ["KONVERTER_HIGH_CONFIDENCE"] = "0.85"
    os.environ["KONVERTER_MEDIUM_CONFIDENCE"] = "0.65"

    import app.main
    from app.pipeline import PipelineOutput

    module = importlib.reload(app.main)

    def process_for_test(_pdf_path, stage):
        stage(1, "Extracting test document")
        blocks = [
            {
                "id": "#/texts/0",
                "label": "title",
                "text": "Accessibility Standards Report",
                "page": 1,
                "confidence": 0.98,
                "order": 0,
            },
            {
                "id": "#/texts/1",
                "label": "chapter_title",
                "text": "1. Introduction",
                "page": 1,
                "confidence": 0.95,
                "order": 1,
            },
            {
                "id": "#/texts/2",
                "label": "section_header_1",
                "text": "1. Introduction",
                "page": 1,
                "confidence": 0.95,
                "order": 2,
            },
            {
                "id": "#/texts/3",
                "label": "section_header_2",
                "text": "Purpose",
                "page": 1,
                "confidence": 0.72,
                "order": 3,
            },
            {
                "id": "#/texts/4",
                "label": "text",
                "text": "This report explains the document review workflow.",
                "page": 1,
                "confidence": 0.96,
                "order": 4,
            },
            {
                "id": "#/tables/0",
                "label": "table",
                "text": "Item | Status\nStructure | Review",
                "table_data": {
                    "headers": ["Item", "Status"],
                    "rows": [["Structure", "Review"]],
                },
                "page": 1,
                "confidence": 0.58,
                "order": 5,
            },
        ]
        metadata = {
            "title": "Accessibility Standards Report",
            "publisher": "Example Commission",
            "published_date": "2026-06-18",
            "jurisdiction": "Victoria, Australia",
            "citations": "",
        }
        fields = {
            name: {
                "band": "high" if name in {"title", "publisher"} else "med",
                "score": 0.9 if name in {"title", "publisher"} else 0.75,
                "page": 1,
                "evidence": "Extracted from Docling text.",
                "source": "Docling text · pages 1–8",
            }
            for name in metadata
        }
        stage(5, "Creating review queue")
        return PipelineOutput(
            blocks=blocks,
            review_items=module.processing.pipeline._build_review_items(blocks),
            metadata_payload={"metadata": metadata, "fields": fields},
            raw_docling={"name": "Accessibility Standards Report"},
            doc_confidence={"mean_score": 0.83},
            warnings=[],
            elapsed_seconds=0.01,
        )

    module.processing.pipeline.process = process_for_test
    from fastapi.testclient import TestClient

    return TestClient(module.app)


def wait_until_complete(client, document_id: str) -> dict:
    for _ in range(100):
        response = client.get(f"/api/documents/{document_id}/status")
        assert response.status_code == 200
        job = response.json()
        if job["state"] in {"complete", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError("Processing did not finish")


def upload_and_process(client, file_name: str = "report.pdf") -> str:
    response = client.post(
        "/api/documents",
        files={"files": (file_name, make_pdf(), "application/pdf")},
    )
    assert response.status_code == 201
    document_id = response.json()[0]["id"]
    assert client.post(f"/api/documents/{document_id}/process").status_code == 200
    assert wait_until_complete(client, document_id)["state"] == "complete"
    return document_id


def confirm_metadata(client, document_id: str) -> dict:
    metadata = client.get(f"/api/documents/{document_id}/metadata").json()["metadata"]
    response = client.put(f"/api/documents/{document_id}/metadata", json=metadata)
    assert response.status_code == 200
    return metadata


def test_upload_review_correct_and_export(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)

        review = client.get(f"/api/documents/{document_id}/review-items").json()
        assert review
        assert all(item["band"] in {"med", "low"} for item in review)
        assert all(item["confidence"] < 0.85 for item in review)

        table_item = next(item for item in review if item["type"] == "table")
        evidence = client.get(
            f"/api/documents/{document_id}/review-items/{table_item['id']}/evidence.png"
        )
        assert evidence.status_code == 200
        assert evidence.content.startswith(b"\x89PNG")

        changed = client.patch(
            f"/api/documents/{document_id}/review-items/{table_item['id']}",
            json={"type": "list", "label": "List"},
        )
        assert changed.status_code == 200
        assert changed.json()["kind"] == "text"
        assert changed.json()["correctedText"] == "Structure — Review"
        assert "|" not in changed.json()["correctedText"]

        resolved = client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        assert resolved.status_code == 200
        assert all(
            item["status"] == "accepted" or item["status"] == "edited"
            for item in resolved.json()
        )

        metadata_response = client.get(f"/api/documents/{document_id}/metadata")
        assert metadata_response.status_code == 200
        metadata = metadata_response.json()["metadata"]
        metadata["publishedDate"] = "18/06/2026"
        assert (
            client.put(
                f"/api/documents/{document_id}/metadata",
                json=metadata,
            ).status_code
            == 200
        )

        assert client.post(f"/api/documents/{document_id}/approval").status_code == 200
        publication = client.get(f"/api/documents/{document_id}/publication")
        assert publication.status_code == 200
        json_ld = publication.json()["jsonLd"]
        graph = json_ld["@graph"]
        report = next(node for node in graph if node["@type"] == "Report")
        assert json_ld["@context"] == "https://schema.org"
        page_ref = report["mainEntityOfPage"]["@id"]
        assert page_ref == f"#webpage-{document_id}"
        web_page = next(node for node in graph if node["@type"] == "WebPage")
        assert web_page["@id"] == page_ref
        assert web_page["mainEntity"] == {"@id": report["@id"]}
        chapters = report.get("hasPart", [])
        assert all(part["@type"] == "Chapter" and "name" in part for part in chapters)
        assert "size" not in report and "author" not in report
        assert any(node["@type"] == "Organization" for node in graph)

        accessible = client.get(f"/api/documents/{document_id}/exports/accessible.html")
        assert accessible.status_code == 200
        assert b"Published on June 18, 2026." in accessible.content
        assert b"data-open-section" in accessible.content
        assert b'<script type="application/ld+json">' in accessible.content
        schema_response = client.get(
            f"/api/documents/{document_id}/exports/schema.jsonld"
        )
        assert schema_response.status_code == 200
        assert schema_response.json()["name"] == "Accessibility Standards Report"
        assert '\n  "@context": "https://schema.org"' in schema_response.text
        structured_response = client.get(
            f"/api/documents/{document_id}/exports/structured.json"
        )
        assert structured_response.status_code == 200
        assert '\n  "document": {' in structured_response.text
        docling_response = client.get(
            f"/api/documents/{document_id}/exports/docling.json"
        )
        assert docling_response.status_code == 200
        assert '\n  "name": "Accessibility Standards Report"' in docling_response.text


def test_table_to_footnote_and_remove_from_output(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client, "footnote-conversion.pdf")
        review = client.get(f"/api/documents/{document_id}/review-items").json()
        table_item = next(item for item in review if item["type"] == "table")

        converted = client.patch(
            f"/api/documents/{document_id}/review-items/{table_item['id']}",
            json={"type": "footnote", "label": "Footnote"},
        )
        assert converted.status_code == 200
        footnote_text = converted.json()["correctedText"]
        assert footnote_text == "Item: Structure; Status: Review."

        removed = client.patch(
            f"/api/documents/{document_id}/review-items/{table_item['id']}",
            json={"status": "removed"},
        )
        assert removed.json()["status"] == "removed"
        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        # Approval is blocked until the metadata has been explicitly confirmed.
        blocked = client.post(f"/api/documents/{document_id}/approval")
        assert blocked.status_code == 409
        confirm_metadata(client, document_id)
        assert client.post(f"/api/documents/{document_id}/approval").status_code == 200
        accessible = client.get(f"/api/documents/{document_id}/exports/accessible.html")
        assert footnote_text.encode() not in accessible.content


def test_upload_is_limited_to_five_documents(tmp_path):
    with load_client(tmp_path) as client:
        response = client.post(
            "/api/documents",
            files=[
                ("files", (f"report-{index}.pdf", make_pdf(), "application/pdf"))
                for index in range(6)
            ],
        )

        assert response.status_code == 400
        assert "at most 5 documents" in response.json()["detail"]


def test_revoke_discards_output_and_reapproval_works(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        confirm_metadata(client, document_id)
        assert client.post(f"/api/documents/{document_id}/approval").status_code == 200
        assert (
            client.get(
                f"/api/documents/{document_id}/exports/accessible.html"
            ).status_code
            == 200
        )

        # Revoking removes the generated output and blocks exports.
        assert client.delete(f"/api/documents/{document_id}/approval").status_code == 204
        assert (
            client.get(
                f"/api/documents/{document_id}/exports/accessible.html"
            ).status_code
            == 409
        )
        assert client.get(f"/api/documents/{document_id}/publication").status_code == 409

        # Approving again succeeds without any further edits.
        assert client.post(f"/api/documents/{document_id}/approval").status_code == 200
        assert (
            client.get(
                f"/api/documents/{document_id}/exports/accessible.html"
            ).status_code
            == 200
        )


def test_review_edit_after_approval_discards_generated_html(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        confirm_metadata(client, document_id)
        assert client.post(f"/api/documents/{document_id}/approval").status_code == 200

        review = client.get(f"/api/documents/{document_id}/review-items").json()
        client.patch(
            f"/api/documents/{document_id}/review-items/{review[0]['id']}",
            json={"correctedText": "Updated heading"},
        )

        # Returning to review discards the previously generated output.
        assert (
            client.get(
                f"/api/documents/{document_id}/exports/accessible.html"
            ).status_code
            == 409
        )
        summary = client.get(f"/api/documents/{document_id}").json()
        assert summary["approvedAt"] is None


def test_documents_can_be_listed_and_state_survives(tmp_path):
    with load_client(tmp_path) as client:
        first = upload_and_process(client, "first.pdf")
        second = upload_and_process(client, "second.pdf")
        client.post(f"/api/documents/{first}/review-items/resolve-all")
        confirm_metadata(client, first)
        client.post(f"/api/documents/{first}/approval")

        listed = client.get("/api/documents").json()
        assert [entry["fileName"] for entry in listed] == ["first.pdf", "second.pdf"]
        by_id = {entry["id"]: entry for entry in listed}
        assert by_id[first]["approvedAt"] is not None
        assert by_id[first]["metadataConfirmed"] is True
        # Approving one document never marks the other one approved.
        assert by_id[second]["approvedAt"] is None
        assert by_id[second]["metadataConfirmed"] is False


def test_converting_table_to_heading_flattens_to_one_line(tmp_path):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client, "heading-conversion.pdf")
        review = client.get(f"/api/documents/{document_id}/review-items").json()
        table_item = next(item for item in review if item["type"] == "table")

        converted = client.patch(
            f"/api/documents/{document_id}/review-items/{table_item['id']}",
            json={"type": "section_header_2", "label": "H2"},
        )
        assert converted.status_code == 200
        corrected = converted.json()["correctedText"]
        assert "\n" not in corrected
        assert "|" not in corrected
