import json as _json
import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Document, Extraction, Job
from backend.schemas.invoice import Invoice
from backend.services.invoice_validator import ValidationResult


async def create_document(db: AsyncSession, **kwargs) -> Document:
    document = Document(**kwargs)
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def get_document(db: AsyncSession, document_id: str) -> Document | None:
    result = await db.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def list_documents(
    db: AsyncSession, skip: int = 0, limit: int = 50
) -> list[Document]:
    result = await db.execute(
        select(Document).order_by(Document.upload_date.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def update_document(
    db: AsyncSession, document_id: str, **kwargs
) -> Document | None:
    document = await get_document(db, document_id)
    if document is None:
        return None
    for key, value in kwargs.items():
        setattr(document, key, value)
    await db.commit()
    await db.refresh(document)
    return document


async def delete_document(db: AsyncSession, document_id: str) -> bool:
    document = await get_document(db, document_id)
    if document is None:
        return False
    await db.delete(document)
    await db.commit()
    return True


async def create_job(db: AsyncSession, **kwargs) -> Job:
    job = Job(**kwargs)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(db: AsyncSession, job_id: str) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def get_jobs_for_document(
    db: AsyncSession, document_id: str
) -> list[Job]:
    result = await db.execute(
        select(Job)
        .where(Job.document_id == document_id)
        .order_by(Job.created_at.desc())
    )
    return list(result.scalars().all())


async def update_job(db: AsyncSession, job_id: str, **kwargs) -> Job | None:
    job = await get_job(db, job_id)
    if job is None:
        return None
    for key, value in kwargs.items():
        setattr(job, key, value)
    await db.commit()
    await db.refresh(job)
    return job


# --- Extraction CRUD ---


def _extraction_status(result: ValidationResult) -> str:
    if not result.valid:
        return "invalid"
    if result.requires_manual_review:
        return "needs_review"
    return "valid"


async def create_extraction(
    db: AsyncSession,
    document_id: str,
    invoice: Invoice,
    result: ValidationResult,
    json_path: str,
) -> Extraction:
    extraction = Extraction(
        id=uuid.uuid4().hex,
        document_id=document_id,
        invoice_type=invoice.invoice_type.value,
        invoice_number=invoice.invoice_number,
        invoice_series=invoice.invoice_series,
        issuer_cif=invoice.issuer_cif,
        issuer_name=invoice.issuer_name,
        recipient_cif=invoice.recipient_cif,
        recipient_name=invoice.recipient_name,
        issue_date=str(invoice.issue_date) if invoice.issue_date else None,
        total_amount=str(invoice.total_amount),
        currency=invoice.currency,
        status=_extraction_status(result),
        validation_errors=_json.dumps([asdict(i) for i in result.issues]) if result.issues else None,
        json_path=json_path,
    )
    db.add(extraction)
    await db.commit()
    await db.refresh(extraction)
    return extraction


async def get_extraction_by_document_id(
    db: AsyncSession, document_id: str
) -> Extraction | None:
    result = await db.execute(
        select(Extraction).where(Extraction.document_id == document_id)
    )
    return result.scalar_one_or_none()


async def upsert_extraction(
    db: AsyncSession,
    document_id: str,
    invoice: Invoice,
    result: ValidationResult,
    json_path: str,
) -> Extraction:
    existing = await get_extraction_by_document_id(db, document_id)
    if existing is None:
        return await create_extraction(db, document_id, invoice, result, json_path)

    # Update in place
    existing.invoice_type = invoice.invoice_type.value
    existing.invoice_number = invoice.invoice_number
    existing.invoice_series = invoice.invoice_series
    existing.issuer_cif = invoice.issuer_cif
    existing.issuer_name = invoice.issuer_name
    existing.recipient_cif = invoice.recipient_cif
    existing.recipient_name = invoice.recipient_name
    existing.issue_date = str(invoice.issue_date) if invoice.issue_date else None
    existing.total_amount = str(invoice.total_amount)
    existing.currency = invoice.currency
    existing.status = _extraction_status(result)
    existing.validation_errors = _json.dumps([asdict(i) for i in result.issues]) if result.issues else None
    existing.json_path = json_path
    await db.commit()
    await db.refresh(existing)
    return existing


async def find_duplicate(
    db: AsyncSession,
    issuer_cif: str,
    invoice_number: str,
    invoice_series: str | None,
) -> Extraction | None:
    stmt = select(Extraction).where(
        Extraction.issuer_cif == issuer_cif,
        Extraction.invoice_number == invoice_number,
    )
    if invoice_series is None:
        stmt = stmt.where(Extraction.invoice_series.is_(None))
    else:
        stmt = stmt.where(Extraction.invoice_series == invoice_series)
    result = await db.execute(stmt)
    return result.scalars().first()
