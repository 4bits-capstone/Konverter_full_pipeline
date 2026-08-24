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
    approved_at: str | None = None
    metadata_confirmed: bool = False
    uploaded_by_email: str | None = None
    uploaded_at: str | None = None


class DocumentProcessingJob(ApiModel):
    state: ProcessingState
    started_at: int | None = None
    duration_ms: int = 0
    current_step: int = 0
    progress: int = 0
    remaining_seconds: int = 0
    message: str | None = None


class ProcessingElementCoverage(ApiModel):
    detected: int = 0
    total: int = 0
    needs_review: int = 0


class ProcessingSummary(ApiModel):
    pages: ProcessingElementCoverage
    headings: ProcessingElementCoverage
    images: ProcessingElementCoverage
    tables: ProcessingElementCoverage


ReviewStatus = Literal["pending", "accepted", "edited", "needs_attention", "removed"]
ConfidenceBand = Literal["high", "med", "low"]
ReviewKind = Literal["kv", "text", "table"]

ReviewType = Literal[
    "box_section",
    "caption",
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


class SourceBounds(ApiModel):
    left: float
    top: float
    right: float
    bottom: float
    page_width: float
    page_height: float


class SourceEvidence(ApiModel):
    page: int
    html: str
    bounds: SourceBounds | None = None


class ReviewTableData(ApiModel):
    caption: str | None = Field(default=None, max_length=2_000)
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
    label: str | None = Field(default=None, max_length=120)
    corrected_text: str | None = Field(default=None, max_length=200_000)
    corrected_table: ReviewTableData | None = None


class ReviewBulkPatch(ApiModel):
    item_ids: list[str] = Field(min_length=1, max_length=2_000)
    changes: ReviewPatch


class DocumentMetadata(ApiModel):
    title: str = Field(default="", max_length=2_000)
    publisher: str = Field(default="", max_length=2_000)
    published_date: str = Field(default="", max_length=200)
    jurisdiction: str = Field(default="", max_length=2_000)
    citations: str = Field(default="", max_length=20_000)


class MetadataFieldInfo(ApiModel):
    band: ConfidenceBand
    score: float
    page: int = 1
    evidence: str = ""
    source: str = "Docling text, pages 1–8"


class MetadataPayload(ApiModel):
    metadata: DocumentMetadata
    fields: dict[str, MetadataFieldInfo]


class DocumentConfidence(ApiModel):
    score: float | None = None
    band: ConfidenceBand | None = None
    source: str = ""


class PublicationPayload(ApiModel):
    publication: dict[str, Any]
    metadata: DocumentMetadata
    json_ld: dict[str, Any]
    confidence: DocumentConfidence | None = None


class ApprovalResult(ApiModel):
    approved_at: str


class ChatMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8_000)


class ChatRequest(ApiModel):
    message: str = Field(max_length=4_000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)


class TtsRequest(ApiModel):
    text: str = Field(max_length=4_000)
