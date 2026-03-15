# backend/api/extract.py
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import crud
from backend.database.engine import AsyncSessionLocal, get_db
from backend.database.models import Job
from backend.schemas.jobs import JobResponse
from backend.services.llm_service import LLMConnectionError, get_llm_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extract", tags=["extract"])


class ExtractionStatusResponse(BaseModel):
    job_status: str
    extraction_status: str | None
    invoice_json_available: bool
    validation_issues: list[dict] | None
    invoice: dict | None


@router.post("/{document_id}", response_model=JobResponse, status_code=201)
async def trigger_extraction(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    doc = await crud.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    existing = await db.execute(
        select(Job).where(
            Job.document_id == document_id,
            Job.job_type == "extraction",
            Job.status.in_(["pending", "running"]),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Extraction job already running for this document")

    job = await crud.create_job(db, document_id=document_id, job_type="extraction", status="pending")
    background_tasks.add_task(_run_extraction, document_id, job.id)
    return job


@router.get("/{document_id}", response_model=ExtractionStatusResponse)
async def get_extraction_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    doc = await crud.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Find most recent extraction job
    result = await db.execute(
        select(Job)
        .where(Job.document_id == document_id, Job.job_type == "extraction")
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()

    extraction = await crud.get_extraction_by_document_id(db, document_id)

    job_status = job.status if job else "not_started"
    extraction_status = extraction.status if extraction else None
    json_available = extraction is not None and Path(extraction.json_path).exists()

    invoice_data: dict | None = None
    if json_available:
        invoice_data = json.loads(Path(extraction.json_path).read_text())

    validation_issues: list[dict] | None = None
    if extraction and extraction.validation_errors:
        validation_issues = json.loads(extraction.validation_errors)

    return ExtractionStatusResponse(
        job_status=job_status,
        extraction_status=extraction_status,
        invoice_json_available=json_available,
        validation_issues=validation_issues,
        invoice=invoice_data,
    )


async def _run_extraction(document_id: str, job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await crud.update_job(db, job_id, status="running")

            doc = await crud.get_document(db, document_id)
            if doc is None or doc.text_content is None:
                await crud.update_job(db, job_id, status="failed", error="No OCR text available — run OCR first")
                return

            from backend.services.invoice_extractor import extract_invoice
            from backend.services.invoice_validator import ValidationIssue

            llm = get_llm_service()
            invoice, result = await extract_invoice(doc.text_content, doc.filename, llm)

            # Check for duplicates
            dup = await crud.find_duplicate(db, invoice.issuer_cif, invoice.invoice_number, invoice.invoice_series)
            if dup and dup.document_id != document_id:
                result.issues.append(
                    ValidationIssue(field="invoice_number", message="DUPLICATE: same issuer CIF + invoice number already exists", severity="warning")
                )

            # Write JSON
            settings = get_settings()
            json_path = settings.EXTRACTIONS_DIR / f"{document_id}.json"
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(invoice.model_dump_json(indent=2))

            await crud.upsert_extraction(db, document_id, invoice, result, str(json_path))
            await crud.update_job(db, job_id, status="completed", progress=1.0)

        except LLMConnectionError as exc:
            await crud.update_job(db, job_id, status="failed", error="Ollama unreachable")
            logger.error("LLM connection error for document %s: %s", document_id, exc)
        except Exception as exc:
            await crud.update_job(db, job_id, status="failed", error=str(exc))
            logger.exception("Extraction failed for document %s", document_id)
