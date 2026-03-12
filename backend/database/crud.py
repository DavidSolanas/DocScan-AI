from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Document, Job


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
