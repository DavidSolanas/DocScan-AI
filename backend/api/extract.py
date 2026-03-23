# backend/api/extract.py
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import crud
from backend.database.engine import AsyncSessionLocal, get_db
from backend.database.models import Job
from backend.schemas.corrections import ReextractFieldResponse
from backend.schemas.jobs import JobResponse
from backend.services.llm_service import LLMConnectionError, LLMResponseError, LLMTimeoutError, get_llm_service

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


@router.get("/{document_id}/export")
async def export_extraction(
    request: Request,
    document_id: str,
    format: str = "md",
    template_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    doc = await crud.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    extraction = await crud.get_extraction_by_document_id(db, document_id)
    if extraction is None or not Path(extraction.json_path).exists():
        raise HTTPException(status_code=404, detail="No extraction available for this document")

    from backend.services.extractor_export import to_csv, to_markdown

    # Apply corrections overlay — the corrected result is the canonical view for all formats
    from backend.services.correction_service import get_corrected_extraction_result
    result = await get_corrected_extraction_result(db, extraction)

    # Resolve template fields if template_id provided
    template_fields = None
    if template_id:
        from backend.database.crud import get_template
        from backend.services.template_service import parse_template_fields
        tmpl = await get_template(db, template_id)
        if tmpl:
            template_fields = parse_template_fields(tmpl.fields_json)

    filename_base = Path(doc.filename).stem

    if format == "xlsx":
        from backend.services.excel_exporter import to_xlsx
        content = to_xlsx(result, doc.filename, template_fields)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
        )
    elif format == "docx":
        from backend.services.word_exporter import to_docx
        content = to_docx(result, doc.filename, template_fields)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.docx"'},
        )
    elif format == "csv":
        content = to_csv(result)
        return Response(
            content=content, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )
    elif format == "sii":
        from backend.services.sii_exporter import generate_sii_xml
        titular_cif = request.query_params.get("titular_cif", "")
        titular_name = request.query_params.get("titular_name", "")
        periodo = request.query_params.get("periodo", "")
        xml_bytes, _warnings = generate_sii_xml(result, titular_cif, titular_name, periodo)
        return Response(
            content=xml_bytes,
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_sii.xml"'},
        )
    elif format == "facturae":
        from backend.services.facturae_exporter import generate_facturae_xml
        xml_bytes = generate_facturae_xml(result)
        return Response(
            content=xml_bytes,
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_facturae.xml"'},
        )
    content = to_markdown(result, doc.filename)
    return Response(
        content=content, media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.md"'},
    )


@router.post("/{document_id}/reextract-field", response_model=ReextractFieldResponse)
async def reextract_field(
    document_id: str,
    field: str,
    db: AsyncSession = Depends(get_db),
):

    doc = await crud.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    extraction = await crud.get_extraction_by_document_id(db, document_id)
    if extraction is None or not Path(extraction.json_path).exists():
        raise HTTPException(status_code=404, detail="No extraction available for this document")

    # Get corrected result for context (to resolve current_value)
    from backend.services.correction_service import get_corrected_extraction_result
    result = await get_corrected_extraction_result(db, extraction)

    # Determine current value for the requested field
    import dataclasses as _dc
    current_value: str | None = None
    if field.startswith("anchor."):
        field_name = field[len("anchor."):]
        anchor_val = getattr(result.anchor, field_name, None)
        current_value = str(anchor_val) if anchor_val is not None else None
    else:
        discovered_val = result.discovered.get(field)
        current_value = str(discovered_val) if discovered_val is not None else None

    text = doc.text_content or ""

    from backend.services.intelligent_extractor import IntelligentExtractor
    extractor = IntelligentExtractor()
    proposed_value, confidence = await extractor.extract_field(field, text, current_value)

    return ReextractFieldResponse(
        field=field,
        proposed_value=proposed_value,
        confidence=confidence,
    )


@router.get("/{document_id}", response_model=ExtractionStatusResponse)
async def get_extraction_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    doc = await crud.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

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


def _decimal_default(obj: object) -> str:
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


async def _run_extraction(document_id: str, job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await crud.update_job(db, job_id, status="running", started_at=datetime.now(UTC))

            doc = await crud.get_document(db, document_id)
            if doc is None or doc.text_content is None:
                await crud.update_job(
                    db, job_id, status="failed",
                    error="No OCR text available — run OCR first",
                    completed_at=datetime.now(UTC),
                )
                return

            from backend.schemas.extraction import ExtractionIssue
            from backend.services.intelligent_extractor import IntelligentExtractor

            llm = get_llm_service()
            extractor = IntelligentExtractor(llm=llm)
            result = await extractor.extract(doc.text_content, doc.filename)

            # Duplicate detection
            a = result.anchor
            if a.issuer_cif and a.invoice_number:
                dup = await crud.find_duplicate(db, a.issuer_cif, a.invoice_number)
                if dup and dup.document_id != document_id:
                    result.issues.append(ExtractionIssue(
                        field="invoice_number",
                        message="DUPLICATE: same issuer CIF + invoice number already exists",
                        severity="warning",
                        source="validator",
                    ))
                    if not result.requires_review:
                        result.requires_review = True

            settings = get_settings()
            json_path = settings.EXTRACTIONS_DIR / f"{document_id}.json"
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(dataclasses.asdict(result), default=_decimal_default, indent=2)
            )

            await crud.upsert_extraction(db, document_id, result, str(json_path))
            await crud.update_job(
                db, job_id, status="completed", progress=1.0, completed_at=datetime.now(UTC)
            )

        except LLMConnectionError as exc:
            await crud.update_job(db, job_id, status="failed", error="Ollama unreachable", completed_at=datetime.now(UTC))
            logger.error("LLM connection error for document %s: %s", document_id, exc)
        except LLMTimeoutError as exc:
            await crud.update_job(db, job_id, status="failed", error="Ollama timed out", completed_at=datetime.now(UTC))
            logger.error("LLM timeout for document %s: %s", document_id, exc)
        except LLMResponseError as exc:
            await crud.update_job(db, job_id, status="failed", error=f"LLM response error: {exc}", completed_at=datetime.now(UTC))
            logger.error("LLM response error for document %s: %s", document_id, exc)
        except Exception as exc:
            await crud.update_job(db, job_id, status="failed", error=str(exc), completed_at=datetime.now(UTC))
            logger.exception("Extraction failed for document %s", document_id)
