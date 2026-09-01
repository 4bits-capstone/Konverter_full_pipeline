from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings  # noqa: I001 (must import first: loads .env
# before audit/auth capture SUPABASE_* into module-level constants at import
# time, so a variable already exported blank in the shell doesn't shadow it)

from . import audit
from .auth import get_current_user, require_admin
from .chat import (
    OpenAINotConfiguredError,
    OpenAIRequestError,
    build_chat_context,
    stream_chat_completion,
    synthesize_speech,
)
from .logging_utils import configure_logging, document_logger
from .media import pdf_page_count, render_pdf_region
from .models import (
    ApprovalResult,
    ChatRequest,
    DocumentMetadata,
    DocumentProcessingJob,
    DocumentSummary,
    MetadataPayload,
    ProcessingSummary,
    PublicationPayload,
    ReviewItem,
    ReviewBulkPatch,
    ReviewPatch,
    TtsRequest,
)
from .service import ProcessingManager, WorkflowService
from .storage import DocumentNotFoundError, LocalDocumentStore

MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_DOCUMENTS_PER_UPLOAD = 5

CurrentUser = Annotated[dict, Depends(get_current_user)]
AdminUser = Annotated[dict, Depends(require_admin)]

settings = load_settings()
configure_logging(settings.log_level)
settings.data_dir.mkdir(parents=True, exist_ok=True)
store = LocalDocumentStore(settings.data_dir)
processing = ProcessingManager(settings, store)
workflow = WorkflowService(settings, store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    processing.executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title="Konverter API",
    version="0.2.0",
    description="Accessible document review and publishing pipeline",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Serves the embeddable chat widget (npm run build:widget) baked into every
# exported HTML by exporter.py. check_dir=False so a fresh checkout that
# hasn't built the widget yet doesn't fail to start.
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).resolve().parent / "static", check_dir=False),
    name="static",
)


def _record(document_id: str) -> dict:
    try:
        return store.get_record(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc


def _uploaded_at(record: dict) -> str | None:
    created_at = record.get("created_at")
    if created_at is None:
        return None
    return datetime.fromtimestamp(float(created_at), tz=timezone.utc).isoformat()


def _summary(record: dict) -> DocumentSummary:
    return DocumentSummary(
        id=record["id"],
        title=record["title"],
        file_name=record["file_name"],
        pages=int(record["pages"]),
        publisher=record["publisher"],
        size_label=record.get("size_label"),
        processing_state=record.get("job", {}).get("state"),
        approved_at=record.get("approved_at"),
        metadata_confirmed=bool(record.get("metadata_confirmed")),
        uploaded_by_email=record.get("uploaded_by_email"),
        uploaded_at=_uploaded_at(record),
    )


def _require_complete(document_id: str) -> dict:
    record = _record(document_id)
    if record["job"]["state"] != "complete":
        raise HTTPException(
            status_code=409, detail="Document processing is not complete"
        )
    return record


def _is_admin(user: dict) -> bool:
    return (user.get("app_metadata") or {}).get("role") == "admin"


def _require_owner(record: dict, user: dict) -> None:
    """Documents uploaded before per-user scoping have no owner and stay
    visible/actionable by everyone. 404 (not 403) so a non-owner can't tell
    the document exists at all."""
    owner = record.get("uploaded_by")
    if owner and owner != user.get("id") and not _is_admin(user):
        raise HTTPException(status_code=404, detail="Document not found")


_LARGE_REVIEW_FIELDS = {"corrected_text", "corrected_table"}


def _safe_review_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe view of a review-item patch: short fields (status, type,
    label) are logged as-is, but large content fields are replaced with a
    marker so the immutable audit_log doesn't end up storing full corrected
    text/table payloads (up to 200k chars) on every edit."""
    return {
        key: ("updated" if key in _LARGE_REVIEW_FIELDS else value)
        for key, value in changes.items()
    }


AUDIT_SNIPPET_MAX = 200


def _snippet(value: Any) -> Any:
    """Bounded, audit-safe preview of a value for before/after logging. The
    audit_log is immutable and hash-chained, so this must never grow
    unbounded — long values are truncated rather than stored in full."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > AUDIT_SNIPPET_MAX:
        return {"preview": text[:AUDIT_SNIPPET_MAX], "truncated": True, "length": len(text)}
    return text


def _review_item_label(item: dict[str, Any]) -> str:
    title = item.get("title") or item.get("label") or item.get("id", "item")
    page = item.get("page")
    return f"{title} (p.{page})" if page is not None else str(title)


def _pretty_json_download(
    payload: Any,
    filename: str,
    media_type: str = "application/json",
) -> Response:
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _render_cover(source_path: Path, destination: Path) -> None:
    try:
        render_pdf_region(source_path, destination, 1, dpi=120, padding=0)
    except Exception:
        # The cover is a visual enhancement; PDF processing should still be allowed.
        destination.unlink(missing_ok=True)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/documents", response_model=list[DocumentSummary])
def list_documents(user: CurrentUser) -> list[DocumentSummary]:
    """List the caller's own documents (plus legacy documents uploaded before
    per-user scoping, which have no recorded owner). This backs the normal
    upload/review/metadata/preview workflow — even for admins, whose personal
    workflow should behave the same as everyone else's. Admin oversight of
    every document lives only in the dedicated /api/documents/all endpoint."""
    records = [
        record for record in store.list_records()
        if record.get("uploaded_by") in (None, user.get("id"))
    ]
    return [_summary(record) for record in records]


@app.get("/api/documents/all", response_model=list[DocumentSummary])
def list_all_documents(user: AdminUser) -> list[DocumentSummary]:
    """Every document regardless of owner. Admin only — backs the Doc list page."""
    return [_summary(record) for record in store.list_records()]


@app.get("/api/audit-log")
async def audit_log(
    user: AdminUser,
    limit: Annotated[int, Query(ge=1, le=audit.MAX_PAGE_LIMIT)] = audit.DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    """Audit trail rows across all users, newest first, one page at a time.
    Admin only."""
    return await audit.list_recent(limit=limit, offset=offset)


@app.get("/api/audit-log/count")
async def audit_log_count(user: AdminUser) -> dict[str, int]:
    """Exact total audit_log row count, uncapped by any page limit — backs
    the audit event counters so they show the real total instead of freezing
    at MAX_PAGE_LIMIT once the log outgrows one page. Admin only."""
    return {"total": await audit.count_all()}


@app.get("/api/audit-log/mine")
async def my_audit_log(
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=audit.MAX_PAGE_LIMIT)] = audit.DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    """The current user's own actions, newest first, one page at a time. Any
    authenticated user; filtered server-side to their own actor_id so they
    can never see anyone else's activity through this endpoint."""
    return await audit.list_recent_for_actor(user.get("id"), limit=limit, offset=offset)


@app.post("/api/documents", response_model=list[DocumentSummary], status_code=201)
async def upload_documents(
    files: Annotated[list[UploadFile], File(description="One or more PDF files")],
    user: CurrentUser,
) -> list[DocumentSummary]:
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one PDF")
    if len(files) > MAX_DOCUMENTS_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Upload at most {MAX_DOCUMENTS_PER_UPLOAD} documents at once",
        )

    uploaded: list[DocumentSummary] = []
    for upload in files:
        safe_name = Path(upload.filename or "document.pdf").name
        if not safe_name.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=415,
                detail="This file type is not supported. Please upload a PDF document.",
            )

        descriptor, temporary_name = tempfile.mkstemp(
            prefix="konverter-upload-",
            suffix=".pdf",
            dir=settings.data_dir,
        )
        temporary_path = Path(temporary_name)
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as destination:
                first_chunk = True
                while chunk := await upload.read(1024 * 1024):
                    if first_chunk and b"%PDF-" not in chunk[:1024]:
                        raise HTTPException(
                            status_code=415,
                            detail="This file type is not supported. Please upload a PDF document.",
                        )
                    first_chunk = False
                    size += len(chunk)
                    if size > MAX_PDF_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"{safe_name} exceeds the 200 MB limit",
                        )
                    destination.write(chunk)
            try:
                pages = pdf_page_count(temporary_path)
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "The PDF appears to be damaged or incomplete. Please open it "
                        "locally to confirm that it works, then upload it again."
                    ),
                ) from exc
            if pages < 1:
                raise HTTPException(
                    status_code=422,
                    detail="The PDF appears to be empty. Please upload a PDF with at least one page.",
                )
            if pages > settings.max_pages:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"This PDF has {pages} pages, which is above the current "
                        f"limit of {settings.max_pages} pages."
                    ),
                )

            document_id = uuid.uuid4().hex
            title = Path(safe_name).stem.replace("-", " ").replace("_", " ").strip()
            record = {
                "id": document_id,
                "title": title,
                "file_name": safe_name,
                "pages": pages,
                "publisher": "Pending metadata extraction",
                "size_bytes": size,
                "size_label": f"{size / (1024 * 1024):.1f} MB",
                "uploaded_by": user.get("id"),
                "uploaded_by_email": user.get("email"),
                "created_at": time.time(),
                "updated_at": time.time(),
                "approved_at": None,
                "metadata_confirmed": False,
                "job": {
                    "state": "idle",
                    "started_at": None,
                    "duration_ms": 0,
                    "current_step": 0,
                    "progress": 0,
                    "remaining_seconds": 0,
                    "message": "Ready to start",
                },
            }
            store.create_document(document_id, temporary_path, record)
            uploaded.append(_summary(record))
            await audit.record_document(document_id, safe_name, user.get("id"))
            await audit.record_audit(
                "upload",
                document_id=document_id,
                actor_id=user.get("id"),
                actor_email=user.get("email"),
                detail={"file_name": safe_name, "pages": pages},
            )
        finally:
            await upload.close()
            temporary_path.unlink(missing_ok=True)
    return uploaded


@app.get("/api/documents/{document_id}", response_model=DocumentSummary)
def get_document(document_id: str) -> DocumentSummary:
    return _summary(_record(document_id))


@app.get(
    "/api/documents/{document_id}/processing-summary",
    response_model=ProcessingSummary,
)
def processing_summary(document_id: str) -> ProcessingSummary:
    _require_complete(document_id)
    try:
        return ProcessingSummary(**workflow.processing_summary(document_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/documents/{document_id}", status_code=204)
async def delete_document(document_id: str, user: CurrentUser) -> Response:
    record = _record(document_id)
    _require_owner(record, user)
    if record["job"]["state"] == "running":
        raise HTTPException(
            status_code=409, detail="Stop processing before removing this document"
        )
    store.delete_document(document_id)
    await audit.record_audit(
        "delete_document",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={"file_name": record.get("file_name")},
    )
    return Response(status_code=204)


@app.post("/api/documents/{document_id}/process", response_model=DocumentProcessingJob)
async def start_processing(document_id: str, user: CurrentUser) -> DocumentProcessingJob:
    record = _record(document_id)
    _require_owner(record, user)
    job = DocumentProcessingJob(**processing.start(document_id, user.get("id"), user.get("email")))
    await audit.record_audit(
        "process_start",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={"file_name": record.get("file_name")},
    )
    return job


@app.delete(
    "/api/documents/{document_id}/process", response_model=DocumentProcessingJob
)
async def stop_processing(document_id: str, user: CurrentUser) -> DocumentProcessingJob:
    record = _record(document_id)
    _require_owner(record, user)
    job = DocumentProcessingJob(**processing.stop(document_id))
    await audit.record_audit(
        "process_stop",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={"file_name": record.get("file_name")},
    )
    return job


def _processing_state_response(document_id: str) -> Response:
    _record(document_id)
    job = DocumentProcessingJob(**processing.status(document_id))
    # Some browser download handlers intercept repeated application/json GETs
    # even when Content-Disposition says inline.  Polling uses a fetch-only
    # text response with no filename/disposition header; response.json() still
    # parses the JSON body normally on the client.
    return Response(
        content=job.model_dump_json(by_alias=True),
        media_type="text/plain",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/documents/{document_id}/status")
def processing_status(document_id: str) -> Response:
    """Backward-compatible status endpoint for older clients."""
    return _processing_state_response(document_id)


@app.post("/api/documents/{document_id}/processing-state")
def processing_state(document_id: str) -> Response:
    """Fetch-only polling endpoint that cannot become a JSON navigation."""
    return _processing_state_response(document_id)


@app.get("/api/documents/{document_id}/review-items", response_model=list[ReviewItem])
def get_review_items(document_id: str) -> list[ReviewItem]:
    _require_complete(document_id)
    try:
        return [ReviewItem(**item) for item in workflow.get_review_items(document_id)]
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch(
    "/api/documents/{document_id}/review-items/{item_id}", response_model=ReviewItem
)
async def update_review_item(
    document_id: str, item_id: str, patch: ReviewPatch, user: CurrentUser
) -> ReviewItem:
    record = _require_complete(document_id)
    _require_owner(record, user)
    changes = patch.model_dump(exclude_unset=True)
    existing = next(
        (i for i in workflow.get_review_items(document_id) if i.get("id") == item_id),
        {},
    )
    before = {k: _snippet(existing.get(k)) for k in changes}
    try:
        item = workflow.update_review_item(document_id, item_id, changes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Review item not found") from exc
    after = {k: _snippet(v) for k, v in changes.items()}
    await audit.record_audit(
        "edit_review_item",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={
            "file_name": record.get("file_name"),
            "item": _review_item_label(item),
            "changes": _safe_review_changes(changes),
            "before": before,
            "after": after,
        },
    )
    return ReviewItem(**item)


@app.post(
    "/api/documents/{document_id}/review-items/bulk",
    response_model=list[ReviewItem],
)
async def update_review_items_bulk(
    document_id: str,
    patch: ReviewBulkPatch,
    user: CurrentUser,
) -> list[ReviewItem]:
    record = _require_complete(document_id)
    _require_owner(record, user)
    changes = patch.changes.model_dump(exclude_unset=True)
    try:
        items = workflow.update_review_items(document_id, patch.item_ids, changes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Review item not found") from exc
    await audit.record_audit(
        "edit_review_item",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={
            "file_name": record.get("file_name"),
            "items": [_review_item_label(item) for item in items],
            "changes": _safe_review_changes(changes),
        },
    )
    return [ReviewItem(**item) for item in items]


@app.post(
    "/api/documents/{document_id}/review-items/resolve-all",
    response_model=list[ReviewItem],
)
async def resolve_all(document_id: str, user: CurrentUser) -> list[ReviewItem]:
    record = _require_complete(document_id)
    _require_owner(record, user)
    before = workflow.get_review_items(document_id)
    changed_ids = {
        item["id"] for item in before if item["status"] in {"pending", "needs_attention"}
    }
    items = workflow.resolve_all(document_id)
    changed_items = [item for item in items if item["id"] in changed_ids]
    await audit.record_audit(
        "edit_review_item",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={
            "file_name": record.get("file_name"),
            "resolve_all": True,
            "count": len(changed_items),
            "items": [_review_item_label(item) for item in changed_items],
        },
    )
    return [ReviewItem(**item) for item in items]


@app.get("/api/documents/{document_id}/metadata", response_model=MetadataPayload)
def get_metadata(document_id: str) -> MetadataPayload:
    _require_complete(document_id)
    try:
        return MetadataPayload(**workflow.get_metadata(document_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/documents/{document_id}/metadata", response_model=DocumentMetadata)
async def save_metadata(
    document_id: str, metadata: DocumentMetadata, user: CurrentUser
) -> DocumentMetadata:
    _require_owner(_require_complete(document_id), user)
    old = workflow.get_metadata(document_id).get("metadata") or {}
    new = metadata.model_dump()
    changed = {k: v for k, v in new.items() if old.get(k) != v}
    before = {k: _snippet(old.get(k)) for k in changed}
    after = {k: _snippet(v) for k, v in changed.items()}
    saved = workflow.save_metadata(document_id, new)
    await audit.record_audit(
        "edit_metadata",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={"title": metadata.title, "before": before, "after": after},
    )
    return DocumentMetadata(**saved)


@app.post("/api/documents/{document_id}/approval", response_model=ApprovalResult)
async def approve_document(document_id: str, user: CurrentUser) -> ApprovalResult:
    record = _require_complete(document_id)
    _require_owner(record, user)
    try:
        approved_at = workflow.approve(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await audit.record_audit(
        "approve",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={"approved_at": approved_at, "file_name": record.get("file_name")},
    )
    return ApprovalResult(approved_at=approved_at)


@app.delete("/api/documents/{document_id}/approval", status_code=204)
async def revoke_approval(document_id: str, user: CurrentUser) -> Response:
    record = _record(document_id)
    _require_owner(record, user)
    workflow.revoke(document_id)
    await audit.record_audit(
        "revoke_approval",
        document_id=document_id,
        actor_id=user.get("id"),
        actor_email=user.get("email"),
        detail={"file_name": record.get("file_name")},
    )
    return Response(status_code=204)


@app.get("/api/documents/{document_id}/publication", response_model=PublicationPayload)
def publication(document_id: str) -> PublicationPayload:
    _record(document_id)
    try:
        return PublicationPayload(**workflow.publication_payload(document_id))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/documents/{document_id}/source")
def source_pdf(document_id: str) -> FileResponse:
    record = _record(document_id)
    return FileResponse(
        store.source_path(document_id),
        media_type="application/pdf",
        filename=record["file_name"],
        content_disposition_type="inline",
    )


@app.get("/api/documents/{document_id}/review-items/{item_id}/evidence.png")
def review_evidence(document_id: str, item_id: str) -> FileResponse:
    record = _require_complete(document_id)
    items = workflow.get_review_items(document_id)
    item = next((value for value in items if value["id"] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    page_number = int(item.get("source", {}).get("page", item.get("page", 1)))
    if page_number < 1 or page_number > int(record.get("pages", 0)):
        raise HTTPException(status_code=422, detail="Source page is outside the PDF")
    safe_item_id = "".join(
        character for character in item_id if character.isalnum() or character in "-_"
    )
    source = item.get("source", {})
    evidence_signature = hashlib.sha256(
        json.dumps(
            {
                "block_id": item.get("block_id"),
                "page": page_number,
                "bounds": source.get("bounds"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16]
    destination = store.artifact_path(
        document_id, f"evidence-{safe_item_id}-{evidence_signature}.png"
    )
    if not destination.exists():
        try:
            render_pdf_region(
                store.source_path(document_id),
                destination,
                page_number,
                source.get("bounds"),
                highlight=bool(source.get("bounds")),
            )
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500, detail="Source evidence could not be rendered"
            ) from exc
    return FileResponse(
        destination,
        media_type="image/png",
        filename=f"source-page-{page_number}-evidence.png",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Evidence-Item": safe_item_id,
        },
    )


@app.get("/api/documents/{document_id}/metadata/{field_name}/evidence.png")
def metadata_evidence(document_id: str, field_name: str) -> FileResponse:
    record = _require_complete(document_id)
    payload = workflow.get_metadata(document_id)
    legacy_name = "published_date" if field_name == "publishedDate" else field_name
    field = payload.get("fields", {}).get(field_name) or payload.get("fields", {}).get(
        legacy_name
    )
    if field is None:
        raise HTTPException(status_code=404, detail="Metadata field not found")

    page_number = int(field.get("page", 1))
    if page_number < 1 or page_number > int(record.get("pages", 0)):
        raise HTTPException(
            status_code=422, detail="Metadata evidence page is outside the PDF"
        )
    safe_field = "".join(
        character
        for character in field_name
        if character.isalnum() or character in "-_"
    )
    destination = store.artifact_path(
        document_id, f"metadata-evidence-{safe_field}-page-{page_number}.png"
    )
    if not destination.exists():
        try:
            render_pdf_region(
                store.source_path(document_id),
                destination,
                page_number,
                dpi=120,
                padding=0,
            )
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500, detail="Metadata evidence could not be rendered"
            ) from exc
    return FileResponse(
        destination,
        media_type="image/png",
        filename=f"{safe_field}-source-page-{page_number}.png",
        content_disposition_type="inline",
    )


@app.get("/api/documents/{document_id}/figures/{image_key}.png")
def figure_image(document_id: str, image_key: str) -> FileResponse:
    _record(document_id)
    if not image_key or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in image_key
    ):
        raise HTTPException(status_code=404, detail="Figure image not found")
    path = store.artifact_path(document_id, f"figure-{image_key}.png")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Figure image not found")
    return FileResponse(
        path,
        media_type="image/png",
        filename=f"figure-{image_key}.png",
        content_disposition_type="inline",
    )


@app.get("/api/documents/{document_id}/cover")
def cover(document_id: str) -> FileResponse:
    _record(document_id)
    path = store.cover_path(document_id)
    if not path.exists():
        _render_cover(store.source_path(document_id), path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Cover preview is unavailable")
    return FileResponse(path, media_type="image/png", filename="cover.png")


@app.get("/api/documents/{document_id}/exports/accessible.html")
def accessible_html(document_id: str) -> FileResponse:
    record = _record(document_id)
    if not record.get("approved_at"):
        raise HTTPException(
            status_code=409, detail="Approve the document before export"
        )
    path = store.artifact_path(document_id, "accessible.html")
    return FileResponse(
        path,
        media_type="text/html",
        filename=f"{Path(record['file_name']).stem}-accessible.html",
    )


@app.get("/api/documents/{document_id}/exports/schema.jsonld")
def schema_json_ld(document_id: str) -> Response:
    record = _record(document_id)
    if not record.get("approved_at"):
        raise HTTPException(
            status_code=409, detail="Approve the document before export"
        )
    return _pretty_json_download(
        store.read_artifact(document_id, "schema.jsonld", {}),
        "schema.jsonld",
        media_type="application/ld+json",
    )


@app.get("/api/documents/{document_id}/exports/structured.json")
def structured_json(document_id: str) -> Response:
    record = _record(document_id)
    if not record.get("approved_at"):
        raise HTTPException(
            status_code=409, detail="Approve the document before export"
        )
    return _pretty_json_download(
        store.read_artifact(document_id, "structured.json", {}),
        "structured.json",
    )


@app.get("/api/documents/{document_id}/exports/docling.json")
def raw_docling_json(document_id: str) -> Response:
    _require_complete(document_id)
    return _pretty_json_download(
        store.read_artifact(document_id, "docling.json", {}),
        "docling.json",
    )


@app.post("/api/documents/{document_id}/chat")
async def chat_with_document(
    document_id: str, payload: ChatRequest, user: CurrentUser
) -> StreamingResponse:
    """Answers questions about a single document. Available as soon as
    processing completes, not just after approval, so reviewers working
    through a long queue can ask about the document while still reviewing
    it — context is built from the current review state (including any
    edits already made) until the document is approved, after which the
    finished export is used instead. Streamed as plain text so the frontend
    can render the reply as it arrives."""
    record = _require_complete(document_id)
    _require_owner(record, user)
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Chat is not configured")

    structured, json_ld = workflow.chat_context_source(document_id)
    context = build_chat_context(structured, json_ld, payload.message)
    history = [{"role": item.role, "content": item.content} for item in payload.history]

    async def stream() -> Any:
        try:
            async for chunk in stream_chat_completion(
                settings, context, payload.message, history
            ):
                yield chunk
        except (OpenAINotConfiguredError, OpenAIRequestError):
            document_logger("app.chat", document_id).warning("chat request failed")

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")


@app.post("/api/public/documents/{document_id}/chat")
async def public_chat_with_document(
    document_id: str, payload: ChatRequest
) -> StreamingResponse:
    """Unauthenticated counterpart to /chat, for the embeddable widget baked
    into every exported HTML file (see exporter.py). There's no reviewer
    identity to scope access by here, so this only works once a document is
    approved and only ever reads the finished export — never draft/
    in-review content."""
    record = _record(document_id)
    if not record.get("approved_at"):
        raise HTTPException(status_code=409, detail="Document is not published")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Chat is not configured")

    structured = store.read_artifact(document_id, "structured.json", {})
    json_ld = store.read_artifact(document_id, "schema.jsonld", {})
    context = build_chat_context(structured, json_ld, payload.message)
    history = [{"role": item.role, "content": item.content} for item in payload.history]

    async def stream() -> Any:
        try:
            async for chunk in stream_chat_completion(
                settings, context, payload.message, history
            ):
                yield chunk
        except (OpenAINotConfiguredError, OpenAIRequestError):
            document_logger("app.chat", document_id).warning(
                "public chat request failed"
            )

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")


@app.post("/api/tts")
async def text_to_speech(payload: TtsRequest, user: CurrentUser) -> StreamingResponse:
    """Converts assistant replies to speech (OpenAI tts-1, nova voice) for
    the document chat's voice-out and hands-free conversation mode."""
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Text-to-speech is not configured")

    async def stream() -> Any:
        try:
            async for chunk in synthesize_speech(settings, payload.text):
                yield chunk
        except (OpenAINotConfiguredError, OpenAIRequestError):
            return

    return StreamingResponse(stream(), media_type="audio/mpeg")
