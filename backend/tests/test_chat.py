from __future__ import annotations

from app.chat import build_chat_context

from test_api import confirm_metadata, load_client, make_pdf, upload_and_process


def test_build_chat_context_uses_metadata_summary_and_sections():
    structured = {
        "metadata": {
            "title": "Example report",
            "publisher": "Example Commission",
            "published_date": "2026-06-18",
            "jurisdiction": "Victoria, Australia",
        },
        "publication": {
            "summary": ["This report reviews accessibility."],
            "sections": [
                {
                    "displayTitle": "1. Introduction",
                    "blocks": [
                        {"type": "paragraph", "text": "This is the introduction."},
                        {
                            "type": "list",
                            "items": [
                                {"text": "First point"},
                                {"text": "Second point"},
                            ],
                        },
                    ],
                }
            ],
        },
    }
    json_ld = {
        "@graph": [
            {
                "@type": "Report",
                "description": "A report about accessibility standards.",
                "accessibilitySummary": "This HTML edition meets WCAG 2.1 AA.",
            }
        ]
    }

    context = build_chat_context(structured, json_ld)

    assert "Title: Example report" in context
    assert "Publisher: Example Commission" in context
    assert "Jurisdiction: Victoria, Australia" in context
    assert "Description: A report about accessibility standards." in context
    assert "Accessibility summary: This HTML edition meets WCAG 2.1 AA." in context
    assert "Summary: This report reviews accessibility." in context
    assert "## 1. Introduction" in context
    assert "This is the introduction." in context
    assert "- First point" in context
    assert "- Second point" in context


def test_build_chat_context_truncates_a_single_oversized_section():
    long_text = "x" * 100_000
    structured = {
        "metadata": {"title": "Long report"},
        "publication": {
            "sections": [
                {
                    "displayTitle": "1. Body",
                    "blocks": [{"type": "paragraph", "text": long_text}],
                }
            ]
        },
    }

    context = build_chat_context(structured, {})

    assert len(context) < 70_000
    assert "omitted" in context


def test_build_chat_context_ranks_sections_by_relevance_when_over_budget():
    # Two short sections plus one deliberately oversized section, so the
    # document as a whole exceeds the budget and the ranking path kicks in.
    filler = "Unrelated filler text about gardening and weather. " * 2_000
    structured = {
        "metadata": {"title": "Long report"},
        "publication": {
            "sections": [
                {
                    "displayTitle": "1. Introduction",
                    "blocks": [{"type": "paragraph", "text": filler}],
                },
                {
                    "displayTitle": "5. After-hours bail decisions",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "text": "Bail justices may grant after-hours bail decisions "
                            "in limited circumstances defined by the Bail Act.",
                        }
                    ],
                },
                {
                    "displayTitle": "9. Appendices",
                    "blocks": [{"type": "paragraph", "text": filler}],
                },
            ]
        },
    }

    context = build_chat_context(
        structured, {}, "What does the report say about after-hours bail decisions?"
    )

    assert "After-hours bail decisions" in context
    assert "Bail justices may grant after-hours bail decisions" in context
    assert "omitted" in context


def test_build_chat_context_keeps_original_order_for_small_documents():
    structured = {
        "metadata": {"title": "Short report"},
        "publication": {
            "sections": [
                {"displayTitle": "1. First", "blocks": [{"type": "paragraph", "text": "First section."}]},
                {"displayTitle": "2. Second", "blocks": [{"type": "paragraph", "text": "Second section."}]},
            ]
        },
    }

    context = build_chat_context(structured, {}, "Tell me about the second section")

    # Even though the question is about the second section, a small document
    # fits whole and stays in its natural reading order, not relevance order.
    assert context.index("## 1. First") < context.index("## 2. Second")
    assert "omitted" not in context


def test_chat_requires_processing_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with load_client(tmp_path) as client:
        response = client.post(
            "/api/documents",
            files={"files": ("report.pdf", make_pdf(), "application/pdf")},
        )
        document_id = response.json()[0]["id"]
        response = client.post(
            f"/api/documents/{document_id}/chat",
            json={"message": "What is this about?"},
        )
        assert response.status_code == 409


def test_chat_works_before_approval_using_current_review_state(tmp_path, monkeypatch):
    # Reviewers working through a long queue shouldn't have to wait until
    # approval to ask about the document — context is built on the fly from
    # blocks.json (via build_publication), not from structured.json, which
    # doesn't exist until the document is approved.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)

        import app.main as app_main

        captured: dict[str, object] = {}

        async def fake_stream_chat_completion(settings, context, message, history):
            captured["context"] = context
            yield "Hello!"

        monkeypatch.setattr(
            app_main, "stream_chat_completion", fake_stream_chat_completion
        )

        response = client.post(
            f"/api/documents/{document_id}/chat",
            json={"message": "What is this about?"},
        )
        assert response.status_code == 200
        assert response.text == "Hello!"
        assert "Accessibility Standards Report" in captured["context"]


def test_chat_returns_503_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        confirm_metadata(client, document_id)
        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        assert (
            client.post(f"/api/documents/{document_id}/approval").status_code == 200
        )

        response = client.post(
            f"/api/documents/{document_id}/chat",
            json={"message": "What is this about?"},
        )
        assert response.status_code == 503


def test_chat_streams_reply_using_document_context(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        confirm_metadata(client, document_id)
        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        assert (
            client.post(f"/api/documents/{document_id}/approval").status_code == 200
        )

        import app.main as app_main

        captured: dict[str, object] = {}

        async def fake_stream_chat_completion(settings, context, message, history):
            captured["context"] = context
            captured["message"] = message
            captured["history"] = history
            for chunk in ["Hello", ", ", "world!"]:
                yield chunk

        monkeypatch.setattr(
            app_main, "stream_chat_completion", fake_stream_chat_completion
        )

        response = client.post(
            f"/api/documents/{document_id}/chat",
            json={
                "message": "Summarize this.",
                "history": [{"role": "user", "content": "Hi"}],
            },
        )
        assert response.status_code == 200
        assert response.text == "Hello, world!"
        assert "Accessibility Standards Report" in captured["context"]
        assert captured["message"] == "Summarize this."
        assert captured["history"] == [{"role": "user", "content": "Hi"}]


def test_public_chat_requires_an_approved_document(tmp_path, monkeypatch):
    # The embeddable widget has no reviewer identity to gate access by, so
    # it must refuse to answer for anything still in review.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)

        response = client.post(
            f"/api/public/documents/{document_id}/chat",
            json={"message": "What is this about?"},
        )
        assert response.status_code == 409


def test_public_chat_returns_404_for_an_unknown_document(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with load_client(tmp_path) as client:
        response = client.post(
            "/api/public/documents/does-not-exist/chat",
            json={"message": "What is this about?"},
        )
        assert response.status_code == 404


def test_public_chat_returns_503_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        confirm_metadata(client, document_id)
        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        assert (
            client.post(f"/api/documents/{document_id}/approval").status_code == 200
        )

        response = client.post(
            f"/api/public/documents/{document_id}/chat",
            json={"message": "What is this about?"},
        )
        assert response.status_code == 503


def test_public_chat_streams_a_reply_with_no_authorization_header(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        confirm_metadata(client, document_id)
        client.post(f"/api/documents/{document_id}/review-items/resolve-all")
        assert (
            client.post(f"/api/documents/{document_id}/approval").status_code == 200
        )

        import app.main as app_main

        captured: dict[str, object] = {}

        async def fake_stream_chat_completion(settings, context, message, history):
            captured["context"] = context
            for chunk in ["Hello", " there!"]:
                yield chunk

        monkeypatch.setattr(
            app_main, "stream_chat_completion", fake_stream_chat_completion
        )

        response = client.post(
            f"/api/public/documents/{document_id}/chat",
            json={"message": "Summarize this."},
            headers={},
        )
        assert response.status_code == 200
        assert response.text == "Hello there!"
        assert "Accessibility Standards Report" in captured["context"]


def test_tts_returns_503_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with load_client(tmp_path) as client:
        response = client.post("/api/tts", json={"text": "Hello"})
        assert response.status_code == 503


def test_tts_streams_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with load_client(tmp_path) as client:
        import app.main as app_main

        async def fake_synthesize_speech(settings, text):
            assert text == "Hello there"
            yield b"ID3"
            yield b"restofmp3"

        monkeypatch.setattr(app_main, "synthesize_speech", fake_synthesize_speech)

        response = client.post("/api/tts", json={"text": "Hello there"})
        assert response.status_code == 200
        assert response.content == b"ID3restofmp3"
        assert response.headers["content-type"] == "audio/mpeg"
