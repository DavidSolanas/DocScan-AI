import json as _json
import uuid
from dataclasses import asdict
from datetime import datetime as _datetime
from typing import Optional

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy import Float as SAFloat
from sqlalchemy import cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database.models import (
    ChatMessage,
    ChatSession,
    Document,
    Extraction,
    ExportTemplate,
    FieldCorrection,
    Job,
)
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


async def list_documents_filtered(
    db: AsyncSession,
    q: Optional[str] = None,
    vendor: Optional[str] = None,
    status: Optional[str] = None,
    invoice_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    amount_min: Optional[str] = None,
    amount_max: Optional[str] = None,
    sort_by: str = "upload_date",
    sort_order: str = "desc",
    skip: int = 0,
    limit: int = 20,
) -> "tuple[list[tuple[Document, Optional[Extraction]]], int]":
    """LEFT JOIN Documents with Extractions and apply optional column filters."""
    stmt = select(Document, Extraction).outerjoin(
        Extraction, Document.id == Extraction.document_id
    )
    if q:
        stmt = stmt.where(Document.filename.ilike(f"%{q}%"))
    if vendor:
        stmt = stmt.where(
            or_(
                Extraction.issuer_name.ilike(f"%{vendor}%"),
                Extraction.recipient_name.ilike(f"%{vendor}%"),
            )
        )
    if status:
        stmt = stmt.where(Document.status == status)
    if invoice_type:
        stmt = stmt.where(Extraction.invoice_type == invoice_type)
    if date_from:
        try:
            iso = _datetime.strptime(date_from, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError(f"date_from must be in dd/mm/yyyy format, got: {date_from!r}")
        stmt = stmt.where(Extraction.issue_date >= iso)
    if date_to:
        try:
            iso = _datetime.strptime(date_to, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError(f"date_to must be in dd/mm/yyyy format, got: {date_to!r}")
        stmt = stmt.where(Extraction.issue_date <= iso)
    if amount_min:
        try:
            min_val = float(amount_min)
        except ValueError:
            raise ValueError(f"amount_min must be a number, got: {amount_min!r}")
        stmt = stmt.where(cast(Extraction.total_amount, SAFloat) >= min_val)
    if amount_max:
        try:
            max_val = float(amount_max)
        except ValueError:
            raise ValueError(f"amount_max must be a number, got: {amount_max!r}")
        stmt = stmt.where(cast(Extraction.total_amount, SAFloat) <= max_val)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    sort_col_map = {
        "upload_date": Document.upload_date,
        "filename": Document.filename,
        "issue_date": Extraction.issue_date,
        "total_amount": cast(Extraction.total_amount, SAFloat),  # numeric sort
    }
    col = sort_col_map.get(sort_by, Document.upload_date)
    if sort_order == "asc":
        stmt = stmt.order_by(col.asc().nullslast())
    else:
        stmt = stmt.order_by(col.desc().nullslast())

    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.all()), total


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
    result: "ExtractionResult | dict",
    json_path: str,
) -> Extraction:
    if isinstance(result, dict):
        # Accept a flat dict for testing convenience — maps top-level keys to Extraction columns
        extraction = Extraction(
            id=uuid.uuid4().hex,
            document_id=document_id,
            invoice_number=result.get("invoice_number"),
            issuer_cif=result.get("issuer_cif"),
            issuer_name=result.get("issuer_name"),
            recipient_cif=result.get("recipient_cif"),
            recipient_name=result.get("recipient_name"),
            issue_date=result.get("issue_date"),
            total_amount=result.get("total_amount"),
            currency=result.get("currency", "EUR"),
            invoice_type=result.get("invoice_type"),
            status=result.get("status", "valid"),
            validation_errors=(
                _json.dumps(result["validation_errors"])
                if result.get("validation_errors")
                else None
            ),
            json_path=json_path,
        )
    else:
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
            validation_errors=(
                _json.dumps([asdict(i) for i in result.issues]) if result.issues else None
            ),
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


# --- Chat CRUD ---


async def create_session(db: AsyncSession, **kwargs) -> ChatSession:
    session = ChatSession(**kwargs)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(db: AsyncSession, session_id: str) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def list_sessions(db: AsyncSession, document_id: str | None = None) -> list[ChatSession]:
    stmt = (
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .order_by(ChatSession.created_at.desc())
    )
    if document_id is not None:
        stmt = stmt.where(ChatSession.document_id == document_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_message(
    db: AsyncSession, session_id: str, role: str, content: str, citations: str | None = None
) -> ChatMessage:
    message = ChatMessage(session_id=session_id, role=role, content=content, citations=citations)
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def list_messages(db: AsyncSession, session_id: str) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    session = await get_session(db, session_id)
    if session is None:
        return False
    await db.delete(session)
    await db.commit()
    return True


# --- FieldCorrection CRUD ---


async def get_latest_corrections(db: AsyncSession, extraction_id: str) -> dict[str, FieldCorrection]:
    """Returns {field_path -> latest FieldCorrection row} using subquery MAX(corrected_at)."""
    subq = (
        select(
            FieldCorrection.extraction_id,
            FieldCorrection.field_path,
            func.max(FieldCorrection.corrected_at).label("max_at"),
        )
        .where(FieldCorrection.extraction_id == extraction_id)
        .group_by(FieldCorrection.extraction_id, FieldCorrection.field_path)
        .subquery()
    )
    stmt = select(FieldCorrection).join(
        subq,
        and_(
            FieldCorrection.extraction_id == subq.c.extraction_id,
            FieldCorrection.field_path == subq.c.field_path,
            FieldCorrection.corrected_at == subq.c.max_at,
        ),
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {row.field_path: row for row in rows}


async def get_all_corrections(db: AsyncSession, extraction_id: str) -> list[FieldCorrection]:
    """Full correction history ordered by corrected_at ASC."""
    stmt = (
        select(FieldCorrection)
        .where(FieldCorrection.extraction_id == extraction_id)
        .order_by(FieldCorrection.corrected_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_correction(
    db: AsyncSession,
    extraction_id: str,
    field_path: str,
    old_value: str | None,
    new_value: str,
    is_locked: bool = False,
) -> FieldCorrection:
    correction = FieldCorrection(
        extraction_id=extraction_id,
        field_path=field_path,
        old_value=old_value,
        new_value=new_value,
        is_locked=is_locked,
    )
    db.add(correction)
    await db.commit()
    await db.refresh(correction)
    return correction


async def set_correction_lock(
    db: AsyncSession, correction_id: str, is_locked: bool
) -> FieldCorrection | None:
    correction = await db.get(FieldCorrection, correction_id)
    if not correction:
        return None
    correction.is_locked = is_locked
    await db.commit()
    await db.refresh(correction)
    return correction


async def delete_corrections_for_field(
    db: AsyncSession, extraction_id: str, field_path: str
) -> int:
    """Delete all corrections for this (extraction_id, field_path). Returns deleted count."""
    stmt = delete(FieldCorrection).where(
        FieldCorrection.extraction_id == extraction_id,
        FieldCorrection.field_path == field_path,
    )
    result = await db.execute(stmt)
    return result.rowcount


# --- ExportTemplate CRUD ---


async def create_template(
    db: AsyncSession, name: str, description: str | None, fields_json: str
) -> ExportTemplate:
    tmpl = ExportTemplate(name=name, description=description, fields_json=fields_json)
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return tmpl


async def get_template(db: AsyncSession, template_id: str) -> ExportTemplate | None:
    return await db.get(ExportTemplate, template_id)


async def get_template_by_name(db: AsyncSession, name: str) -> ExportTemplate | None:
    result = await db.execute(select(ExportTemplate).where(ExportTemplate.name == name))
    return result.scalar_one_or_none()


async def list_templates(db: AsyncSession) -> list[ExportTemplate]:
    result = await db.execute(
        select(ExportTemplate).order_by(ExportTemplate.created_at.asc())
    )
    return list(result.scalars().all())


async def update_template(
    db: AsyncSession, template_id: str, **kwargs
) -> ExportTemplate | None:
    tmpl = await db.get(ExportTemplate, template_id)
    if not tmpl:
        return None
    for key, value in kwargs.items():
        setattr(tmpl, key, value)
    await db.commit()
    await db.refresh(tmpl)
    return tmpl


async def delete_template(db: AsyncSession, template_id: str) -> bool:
    tmpl = await db.get(ExportTemplate, template_id)
    if not tmpl:
        return False
    await db.delete(tmpl)
    await db.commit()
    return True
