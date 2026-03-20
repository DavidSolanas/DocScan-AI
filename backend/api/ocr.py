"""OCR trigger and result endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database.crud import create_job, get_document, update_document, update_job
from backend.database.engine import AsyncSessionLocal, get_db
from backend.database.models import Job
from backend.schemas.jobs import JobResponse
from backend.schemas.ocr import OCRPageSchema, OCRResultResponse, OCRTriggerRequest
from backend.services.ocr_engine import build_ocr_result, ocr_page_routed
from backend.services.preprocessing import preprocess_image
from backend.services.table_extractor import (
    extract_tables_from_image,
    extract_tables_from_pdf,
    merge_tables_across_pages,
)
from backend.utils.image_utils import load_image, pdf_page_count, pdf_page_to_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


async def ocr_document_task(
    document_id: str,
    job_id: str,
    file_path: str,
    lang: str,
    do_preprocess: bool,
) -> None:
    """Background task: run OCR on a document page-by-page with GLM-OCR → Tesseract routing."""
    settings = get_settings()
    dpi = settings.OCR_TARGET_DPI
    psm = settings.TESSERACT_PSM
    confidence_threshold = settings.OCR_CONFIDENCE_THRESHOLD
    glm_ocr_enabled = settings.GLM_OCR_ENABLED

    async with AsyncSessionLocal() as db:
        await update_job(
            db, job_id, status="running", started_at=datetime.now(UTC)
        )

        try:
            path = Path(file_path)
            ext = path.suffix.lower()
            page_results = []
            engine_per_page: list[str] = []

            tables_by_page: dict[int, list] = {}

            if ext == ".pdf":
                import asyncio

                total_pages = pdf_page_count(file_path)
                for i in range(total_pages):
                    image = await asyncio.to_thread(pdf_page_to_image, file_path, i, dpi)
                    if do_preprocess:
                        preprocessed = await preprocess_image(image)
                        image = preprocessed.image
                    page_result, engine_used = await ocr_page_routed(
                        image, i + 1, lang, psm, confidence_threshold, glm_ocr_enabled
                    )
                    page_results.append(page_result)
                    engine_per_page.append(engine_used.value)
                    del image
                    if settings.TABLE_EXTRACTION_ENABLED:
                        page_tables = await asyncio.to_thread(
                            extract_tables_from_pdf, file_path, i + 1
                        )
                        if page_tables:
                            tables_by_page[i + 1] = page_tables
                    await update_job(
                        db, job_id, progress=(i + 1) / total_pages
                    )
            elif ext in _IMAGE_EXTENSIONS:
                import asyncio

                image = await asyncio.to_thread(load_image, file_path)
                if do_preprocess:
                    preprocessed = await preprocess_image(image)
                    image = preprocessed.image
                page_result, engine_used = await ocr_page_routed(
                    image, 1, lang, psm, confidence_threshold, glm_ocr_enabled
                )
                page_results.append(page_result)
                engine_per_page.append(engine_used.value)
                if settings.TABLE_EXTRACTION_ENABLED:
                    page_tables = await asyncio.to_thread(
                        extract_tables_from_image, image, 1
                    )
                    if page_tables:
                        tables_by_page[1] = page_tables
                del image
                await update_job(db, job_id, progress=1.0)
            else:
                raise ValueError(f"Unsupported file format for OCR: {ext}")

            merged_tables: list = []
            if tables_by_page:
                merged_tables = merge_tables_across_pages(tables_by_page)

            result = build_ocr_result(page_results)

            # Store summary in job result as JSON
            result_json = json.dumps({
                "full_text": result.full_text,
                "average_confidence": result.average_confidence,
                "page_count": len(result.pages),
                "low_confidence_pages": result.low_confidence_pages,
                "pages": [
                    {
                        "page_number": p.page_number,
                        "text": p.text,
                        "average_confidence": p.average_confidence,
                        "low_confidence": p.low_confidence,
                        "word_count": len(p.words),
                        "engine_used": engine_per_page[idx],
                    }
                    for idx, p in enumerate(result.pages)
                ],
            })

            await update_document(
                db,
                document_id,
                text_content=result.full_text,
                ocr_confidence=result.average_confidence,
                status="completed",
            )
            await update_job(
                db,
                job_id,
                status="completed",
                progress=1.0,
                result=result_json,
                completed_at=datetime.now(UTC),
            )

            # Auto-trigger extraction if document looks like an invoice
            from backend.services.invoice_extractor import is_likely_invoice
            if is_likely_invoice(result.full_text):
                from backend.api.extract import _run_extraction
                from sqlalchemy import select as _select
                from backend.database.models import Job as _Job
                # Only trigger if no pending/running extraction job exists
                existing_jobs = await db.execute(
                    _select(_Job).where(
                        _Job.document_id == document_id,
                        _Job.job_type == "extraction",
                        _Job.status.in_(["pending", "running"]),
                    )
                )
                if existing_jobs.scalar_one_or_none() is None:
                    extraction_job = await create_job(db, document_id=document_id, job_type="extraction")
                    await _run_extraction(document_id, extraction_job.id)

        except Exception as exc:
            logger.exception("OCR failed for document %s", document_id)
            await update_document(db, document_id, status="failed")
            await update_job(
                db,
                job_id,
                status="failed",
                error=str(exc),
                completed_at=datetime.now(UTC),
            )


@router.post("/{document_id}", response_model=JobResponse, status_code=201)
async def trigger_ocr(
    document_id: str,
    body: OCRTriggerRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Trigger OCR processing for a document."""
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check for existing pending/running OCR jobs (409 guard)
    existing = await db.execute(
        select(Job).where(
            Job.document_id == document_id,
            Job.job_type == "ocr",
            Job.status.in_(["pending", "running"]),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="OCR job already in progress")

    req = body or OCRTriggerRequest()

    # Create a placeholder job to return immediately
    job = await create_job(
        db,
        document_id=document_id,
        job_type="ocr",
        status="pending",
    )

    background_tasks.add_task(
        ocr_document_task,
        document_id,
        job.id,
        document.file_path,
        req.lang,
        req.preprocess,
    )

    return JobResponse.model_validate(job)


@router.get("/{document_id}/result", response_model=OCRResultResponse)
async def get_ocr_result(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> OCRResultResponse:
    """Get the latest completed OCR result for a document."""
    document = await get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Find latest completed OCR job
    result = await db.execute(
        select(Job)
        .where(
            Job.document_id == document_id,
            Job.job_type == "ocr",
            Job.status == "completed",
        )
        .order_by(Job.completed_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="No OCR results available")

    data = json.loads(job.result)
    return OCRResultResponse(
        document_id=document_id,
        full_text=data["full_text"],
        average_confidence=data["average_confidence"],
        page_count=data["page_count"],
        low_confidence_pages=data["low_confidence_pages"],
        pages=[OCRPageSchema(**p) for p in data["pages"]],
    )
