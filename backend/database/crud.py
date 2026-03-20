import json as _json
import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Document, Extraction, Job
from backend.schemas.extraction import ExtractionResult


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


def _extraction_status(result: ExtractionResult) -> str:
    if any(i.severity == "error" for i in result.issues):
        return "invalid"
    if result.requires_review:
        return "needs_review"
    return "valid"


async def create_extraction(
    db: AsyncSession,
    document_id: str,
    result: ExtractionResult,
    json_path: str,
) -> Extraction:
    a = result.anchor
    extraction = Extraction(
        id=uuid.uuid4().hex,
        document_id=document_id,
        invoice_number=a.invoice_number,
        issuer_cif=a.issuer_cif,
        issuer_name=a.issuer_name,
        recipient_cif=a.recipient_cif,
        recipient_name=a.recipient_name,
        issue_date=a.issue_date,
        total_amount=str(a.total_amount) if a.total_amount is not None else None,
        currency=a.currency,
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
    result: ExtractionResult,
    json_path: str,
) -> Extraction:
    existing = await get_extraction_by_document_id(db, document_id)
    if existing is None:
        return await create_extraction(db, document_id, result, json_path)
    a = result.anchor
    existing.invoice_number = a.invoice_number
    existing.issuer_cif = a.issuer_cif
    existing.issuer_name = a.issuer_name
    existing.recipient_cif = a.recipient_cif
    existing.recipient_name = a.recipient_name
    existing.issue_date = a.issue_date
    existing.total_amount = str(a.total_amount) if a.total_amount is not None else None
    existing.currency = a.currency
    existing.status = _extraction_status(result)
    existing.validation_errors = (
        _json.dumps([asdict(i) for i in result.issues]) if result.issues else None
    )
    existing.json_path = json_path
    await db.commit()
    await db.refresh(existing)
    return existing


async def find_duplicate(
    db: AsyncSession,
    issuer_cif: str,
    invoice_number: str,
) -> Extraction | None:
    stmt = select(Extraction).where(
        Extraction.issuer_cif == issuer_cif,
        Extraction.invoice_number == invoice_number,
    )
    result = await db.execute(stmt)
    return result.scalars().first()
