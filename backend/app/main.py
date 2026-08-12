from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import load_settings
from .logging_utils import configure_logging
from .media import pdf_page_count, render_pdf_region
from .models import (
    ApprovalResult,
    DocumentMetadata,
    DocumentProcessingJob,
    DocumentSummary,
    MetadataPayload,
    ProcessingSummary,
    PublicationPayload,
    ReviewItem,
    ReviewBulkPatch,
    ReviewPatch,
)
from .service import ProcessingManager, WorkflowService
from .storage import DocumentNotFoundError, LocalDocumentStore

MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_DOCUMENTS_PER_UPLOAD = 5

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


def _record(document_id: str) -> dict:
    try:
        return store.get_record(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc


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
    )


def _require_complete(document_id: str) -> dict:
    record = _record(document_id)
    if record["job"]["state"] != "complete":
        raise HTTPException(
            status_code=409, detail="Document processing is not complete"
        )
    return record


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
def list_documents() -> list[DocumentSummary]:
    """List stored documents so a reloaded client can pick up where it left off."""
    return [_summary(record) for record in store.list_records()]


@app.post("/api/documents", response_model=list[DocumentSummary], status_code=201)
async def upload_documents(
    files: Annotated[list[UploadFile], File(description="One or more PDF files")],
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
def delete_document(document_id: str) -> Response:
    record = _record(document_id)
    if record["job"]["state"] == "running":
        raise HTTPException(
            status_code=409, detail="Stop processing before removing this document"
        )
    store.delete_document(document_id)
    return Response(status_code=204)


@app.post("/api/documents/{document_id}/process", response_model=DocumentProcessingJob)
def start_processing(document_id: str) -> DocumentProcessingJob:
    _record(document_id)
    return DocumentProcessingJob(**processing.start(document_id))


@app.delete(
    "/api/documents/{document_id}/process", response_model=DocumentProcessingJob
)
def stop_processing(document_id: str) -> DocumentProcessingJob:
    _record(document_id)
    return DocumentProcessingJob(**processing.stop(document_id))


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
def update_review_item(
    document_id: str, item_id: str, patch: ReviewPatch
) -> ReviewItem:
    _require_complete(document_id)
    try:
        item = workflow.update_review_item(
            document_id,
            item_id,
            patch.model_dump(exclude_unset=True),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Review item not found") from exc
    return ReviewItem(**item)


@app.post(
    "/api/documents/{document_id}/review-items/bulk",
    response_model=list[ReviewItem],
)
def update_review_items_bulk(
    document_id: str,
    patch: ReviewBulkPatch,
) -> list[ReviewItem]:
    _require_complete(document_id)
    try:
        items = workflow.update_review_items(
            document_id,
            patch.item_ids,
            patch.changes.model_dump(exclude_unset=True),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Review item not found") from exc
    return [ReviewItem(**item) for item in items]


@app.post(
    "/api/documents/{document_id}/review-items/resolve-all",
    response_model=list[ReviewItem],
)
def resolve_all(document_id: str) -> list[ReviewItem]:
    _require_complete(document_id)
    return [ReviewItem(**item) for item in workflow.resolve_all(document_id)]


@app.get("/api/documents/{document_id}/metadata", response_model=MetadataPayload)
def get_metadata(document_id: str) -> MetadataPayload:
    _require_complete(document_id)
    try:
        return MetadataPayload(**workflow.get_metadata(document_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/documents/{document_id}/metadata", response_model=DocumentMetadata)
def save_metadata(document_id: str, metadata: DocumentMetadata) -> DocumentMetadata:
    _require_complete(document_id)
    saved = workflow.save_metadata(document_id, metadata.model_dump())
    return DocumentMetadata(**saved)


@app.post("/api/documents/{document_id}/approval", response_model=ApprovalResult)
def approve_document(document_id: str) -> ApprovalResult:
    _require_complete(document_id)
    try:
        return ApprovalResult(approved_at=workflow.approve(document_id))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/documents/{document_id}/approval", status_code=204)
def revoke_approval(document_id: str) -> Response:
    _record(document_id)
    workflow.revoke(document_id)
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
