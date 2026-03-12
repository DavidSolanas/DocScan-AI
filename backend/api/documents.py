from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database.crud import (
    create_document,
    create_job,
    delete_document,
    get_document,
    list_documents,
    update_document,
    update_job,
)
from backend.database.engine import AsyncSessionLocal, get_db
from backend.database.models import Document
from backend.schemas.documents import (
    DocumentDetail,
    DocumentListResponse,
    DocumentTextResponse,
    DocumentUploadResponse,
)
from backend.services.pdf_parser import parse_pdf
from backend.utils.file_utils import delete_document_files, save_upload, validate_extension

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Media type map for common formats
_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
    ".zip": "application/zip",
    ".rar": "application/x-rar-compressed",
}


async def extract_text_task(document_id: str, file_path: str) -> None:
    """Background task: parse PDF and store results; runs with its own DB session."""
    async with AsyncSessionLocal() as db:
        job = await create_job(
            db,
            document_id=document_id,
            job_type="text_extraction",
            status="running",
            started_at=datetime.now(UTC),
        )
        job_id = job.id
        try:
            result = await parse_pdf(file_path)
            await update_document(
                db,
                document_id,
                text_content=result.text,
                page_count=result.page_count,
                is_scanned=result.is_scanned,
                status="completed",
            )
            await update_job(
                db,
                job_id,
                status="completed",
                progress=1.0,
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.exception("Text extraction failed for document %s", document_id)
            await update_document(db, document_id, status="failed")
            await update_job(
                db,
                job_id,
                status="failed",
                error=str(exc),
                completed_at=datetime.now(UTC),
            )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    filename = file.filename or "upload"

    if not validate_extension(filename):
        raise HTTPException(
            status_code=400,
            detail=f"File extension not allowed: {Path(filename).suffix.lower()}",
        )

    settings = get_settings()
    file_path, file_size = save_upload(file, settings)
    fmt = Path(filename).suffix.lower()

    document = await create_document(
        db,
        filename=filename,
        format=fmt,
        file_path=str(file_path),
        file_size=file_size,
    )

    if fmt == ".pdf":
        background_tasks.add_task(extract_text_task, document.id, str(file_path))

    return DocumentUploadResponse.model_validate(document)


@router.get("/", response_model=DocumentListResponse)
async def list_documents_endpoint(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    documents = await list_documents(db, skip=skip, limit=limit)
    count_result = await db.execute(select(func.count()).select_from(Document))
    total = count_result.scalar_one()
    return DocumentListResponse(
        documents=[DocumentDetail.model_validate(d) for d in documents],
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document_endpoint(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetail.model_validate(document)


@router.get("/{document_id}/text", response_model=DocumentTextResponse)
async def get_document_text(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentTextResponse:
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentTextResponse.model_validate(document)


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = Path(document.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    fmt = document.format.lower()
    media_type = _MEDIA_TYPES.get(fmt, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=document.filename,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document_endpoint(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = document.file_path
    deleted = await delete_document(db, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")

    delete_document_files(file_path)
