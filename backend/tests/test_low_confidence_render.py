"""Pictures, tables, and headings stay visible below the confidence
thresholds. Body text at the same score stays on the review path. The
numeric thresholds themselves are not what this guards."""

from __future__ import annotations

from app.exporter import build_publication
from app.pipeline import KonverterPipeline

from test_pipeline import _settings


def _block(block_id: str, label: str, text: str, confidence: float, order: int, **extra):
    block = {
        "id": block_id,
        "label": label,
        "text": text,
        "page": 1,
        "order": order,
        "confidence": confidence,
        "source_bounds": {"left": 10, "top": 10, "right": 200, "bottom": 40},
    }
    block.update(extra)
    return block


def test_low_confidence_pictures_tables_and_headings_stay_in_review_and_export():
    pipeline = KonverterPipeline(_settings())
    blocks = [
        _block("title", "title", "Report", 1.0, 0),
        _block("heading", "section_header_1", "1 Introduction", 0.40, 1),
        _block("subhead", "section_header_2", "Scope of the review", 0.40, 2),
        _block("pic", "picture", "Chart of filings", 0.40, 3),
        _block(
            "tbl",
            "table",
            "Year 2020",
            0.40,
            4,
            table_data={"headers": ["Year"], "rows": [["2020"]]},
        ),
        _block(
            "body",
            "text",
            "This body paragraph is uncertain and must stay flagged for review.",
            0.40,
            5,
        ),
        _block(
            "sure",
            "text",
            "This body paragraph is high confidence and skips the queue.",
            0.95,
            6,
        ),
    ]

    items = {item["block_id"]: item for item in pipeline._build_review_items(blocks)}
    assert items["pic"]["type"] == "picture"
    assert items["tbl"]["type"] == "table"
    assert items["heading"]["type"] == "section_header_1"
    assert items["subhead"]["type"] == "section_header_2"
    assert items["body"]["type"] == "text"
    assert items["body"]["status"] == "pending"
    assert "sure" not in items

    publication = build_publication(
        blocks, {"title": "Report", "pages": 1, "file_name": "report.pdf"}
    )
    rendered = str(publication)
    assert "Chart of filings" in rendered
    assert "2020" in rendered
    assert "Introduction" in rendered
    assert "Scope of the review" in rendered
    assert "must stay flagged for review" in rendered
