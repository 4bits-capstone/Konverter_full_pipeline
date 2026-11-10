"""Bold/italic edits on a footnote must be readable in the audit log (LI-07).

Styles are stored on the block, not the review item, so the audit "before"
used to be empty and the "after" was raw character offsets. The log should
say which words became bold or italic, and a style-only edit should not be
reported as a text change.
"""

from __future__ import annotations

from test_api import load_client, upload_and_process

FOOTNOTE = "See Smith v Jones (1990) 12 CLR 3."


def _run(start, end, italic=False, bold=False):
    return {"start": start, "end": end, "italic": italic, "bold": bold}


def _make_footnote(document_id: str) -> str:
    """Turn the document's first review item into a plain footnote."""
    import app.main

    store = app.main.store
    items = store.read_artifact(document_id, "review_items.json", [])
    blocks = store.read_artifact(document_id, "blocks.json", [])
    item = items[0]
    item.update(
        type="footnote",
        label="Footnote",
        extracted_text=FOOTNOTE,
        corrected_text=None,
        status="pending",
    )
    for block in blocks:
        if block["id"] == item["block_id"]:
            block.update(label="footnote", text=FOOTNOTE)
            block.pop("styles", None)
            block.pop("styles_text", None)
    store.write_artifact(document_id, "review_items.json", items)
    store.write_artifact(document_id, "blocks.json", blocks)
    return item["id"]


def _capture_audit(monkeypatch) -> list[tuple[str, dict]]:
    import app.main

    events: list[tuple[str, dict]] = []

    async def record(action, **kwargs):
        events.append((action, kwargs))

    monkeypatch.setattr(app.main.audit, "record_audit", record)
    return events


def _edit(client, document_id, item_id, styles):
    response = client.patch(
        f"/api/documents/{document_id}/review-items/{item_id}",
        json={
            "type": "footnote",
            "label": "Footnote",
            "status": "edited",
            "correctedText": FOOTNOTE,
            "correctedStyles": styles,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_style_edit_is_logged_with_readable_before_and_after(tmp_path, monkeypatch):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        item_id = _make_footnote(document_id)
        events = _capture_audit(monkeypatch)

        # Italicise the case name, then make it bold as well.
        _edit(client, document_id, item_id, [_run(4, 17, italic=True)])
        _edit(client, document_id, item_id, [_run(4, 17, italic=True, bold=True)])

    first, second = (kwargs["detail"] for action, kwargs in events)
    assert first["before"]["corrected_styles"] is None
    assert first["after"]["corrected_styles"] == 'italic: "Smith v Jones"'
    assert second["before"]["corrected_styles"] == 'italic: "Smith v Jones"'
    assert second["after"]["corrected_styles"] == 'bold + italic: "Smith v Jones"'
    # Same text resent by the editor: not reported as a text change.
    assert "corrected_text" not in second["after"]
    assert all(action == "edit_review_item" for action, _ in events)


def test_removing_all_styles_is_logged(tmp_path, monkeypatch):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        item_id = _make_footnote(document_id)
        _edit(client, document_id, item_id, [_run(25, 31, bold=True)])
        events = _capture_audit(monkeypatch)

        _edit(client, document_id, item_id, [])

    detail = events[0][1]["detail"]
    assert detail["before"]["corrected_styles"] == 'bold: "12 CLR"'
    assert detail["after"]["corrected_styles"] is None


def test_unchanged_styles_are_not_reported(tmp_path, monkeypatch):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        item_id = _make_footnote(document_id)
        _edit(client, document_id, item_id, [_run(4, 17, italic=True)])
        events = _capture_audit(monkeypatch)

        _edit(client, document_id, item_id, [_run(4, 17, italic=True)])

    detail = events[0][1]["detail"]
    assert "corrected_styles" not in detail["after"]
    assert "corrected_styles" not in detail["before"]


def test_first_style_edit_on_an_untouched_footnote_is_not_a_text_change(
    tmp_path, monkeypatch
):
    # The item has never been edited (corrected_text is None), but the editor
    # still resends the text it showed. That must not read as Empty -> text.
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        item_id = _make_footnote(document_id)
        events = _capture_audit(monkeypatch)

        _edit(client, document_id, item_id, [_run(4, 17, italic=True)])

    detail = events[0][1]["detail"]
    assert "corrected_text" not in detail["after"]
    assert set(detail["after"]) == {"status", "corrected_styles"}


def test_text_edit_logs_the_text_the_reviewer_saw_as_previous(tmp_path, monkeypatch):
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        item_id = _make_footnote(document_id)
        events = _capture_audit(monkeypatch)

        client.patch(
            f"/api/documents/{document_id}/review-items/{item_id}",
            json={"correctedText": "See Smith v Jones (1991) 12 CLR 3."},
        )

    detail = events[0][1]["detail"]
    assert detail["before"]["corrected_text"] == FOOTNOTE
    assert detail["after"]["corrected_text"] == "See Smith v Jones (1991) 12 CLR 3."


def test_late_change_in_long_text_is_still_logged(tmp_path, monkeypatch):
    # Snippets are cut at 200 chars; two texts that only differ after that
    # must still be recognised as a change.
    long_text = "x" * 300
    with load_client(tmp_path) as client:
        document_id = upload_and_process(client)
        item_id = _make_footnote(document_id)
        client.patch(
            f"/api/documents/{document_id}/review-items/{item_id}",
            json={"correctedText": long_text},
        )
        events = _capture_audit(monkeypatch)

        client.patch(
            f"/api/documents/{document_id}/review-items/{item_id}",
            json={"correctedText": long_text[:-1] + "y"},
        )

    detail = events[0][1]["detail"]
    assert "corrected_text" in detail["after"]
    assert detail["after"]["corrected_text"]["truncated"] is True
