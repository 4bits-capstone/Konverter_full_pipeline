from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


ProcessingState = Literal["idle", "running", "failed", "complete"]


class DocumentSummary(ApiModel):
    id: str
    title: str
    file_name: str
    pages: int
    publisher: str
    size_label: str | None = None
    processing_state: ProcessingState | None = None


class DocumentProcessingJob(ApiModel):
    state: ProcessingState
    started_at: int | None = None
    duration_ms: int = 0
    current_step: int = 0
    progress: int = 0
    remaining_seconds: int = 0
    message: str | None = None


ReviewStatus = Literal["pending", "accepted", "edited", "needs_attention", "removed"]
ConfidenceBand = Literal["high", "med", "low"]
ReviewKind = Literal["kv", "text", "table"]

ReviewType = Literal[
    "caption",
    "chapter_title",
    "document_index",
    "footnote",
    "footer",
    "form",
    "formula",
    "header",
    "list",
    "picture",
    "section_header_1",
    "section_header_2",
    "section_header_3",
    "section_header_4",
    "section_header_5",
    "table",
    "title",
    "text",
    "unspecified",
]


class SourceEvidence(ApiModel):
    page: int
    html: str


class ReviewTableData(ApiModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class ReviewItem(ApiModel):
    id: str
    block_id: str
    type: ReviewType
    label: str
    page: int
    confidence: float
    band: ConfidenceBand
    title: str
    kind: ReviewKind
    status: ReviewStatus = "pending"
    extracted_text: str | None = None
    corrected_text: str | None = None
    note: str | None = None
    key_values: list[tuple[str, str]] | None = None
    table_data: ReviewTableData | None = None
    corrected_table: ReviewTableData | None = None
    source: SourceEvidence


class ReviewPatch(ApiModel):
    status: ReviewStatus | None = None
    type: ReviewType | None = None
    label: str | None = None
    corrected_text: str | None = None
    corrected_table: ReviewTableData | None = None


class DocumentMetadata(ApiModel):
    title: str = ""
    publisher: str = ""
    published_date: str = ""
    jurisdiction: str = ""
    citations: str = ""


class MetadataFieldInfo(ApiModel):
    band: ConfidenceBand
    score: float
    page: int = 1
    evidence: str = ""
    source: str = "Docling text, pages 1–8"


class MetadataPayload(ApiModel):
    metadata: DocumentMetadata
    fields: dict[str, MetadataFieldInfo]


class PublicationPayload(ApiModel):
    publication: dict[str, Any]
    metadata: DocumentMetadata
    json_ld: dict[str, Any]


class ApprovalResult(ApiModel):
    approved_at: str
