from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.crud import (
    create_document,
    create_job,
    delete_document,
    get_document,
    get_jobs_for_document,
    list_documents,
    update_document,
)


async def _make_document(db: AsyncSession, filename: str = "test.pdf") -> object:
    return await create_document(
        db,
        filename=filename,
        format=".pdf",
        file_path=f"/tmp/{filename}",
        file_size=1024,
    )


@pytest.mark.asyncio
async def test_create_document(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    assert doc.id is not None
    assert doc.filename == "test.pdf"
    assert doc.format == ".pdf"
    assert doc.file_size == 1024
    assert doc.status == "uploaded"


@pytest.mark.asyncio
async def test_get_document(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    fetched = await get_document(db_session, doc.id)
    assert fetched is not None
    assert fetched.id == doc.id
    assert fetched.filename == doc.filename


@pytest.mark.asyncio
async def test_list_documents(db_session: AsyncSession) -> None:
    await _make_document(db_session, "doc1.pdf")
    await _make_document(db_session, "doc2.pdf")
    await _make_document(db_session, "doc3.pdf")

    docs = await list_documents(db_session)
    assert len(docs) == 3


@pytest.mark.asyncio
async def test_update_document(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    assert doc.status == "uploaded"

    updated = await update_document(db_session, doc.id, status="completed")
    assert updated is not None
    assert updated.status == "completed"

    # Verify persisted
    fetched = await get_document(db_session, doc.id)
    assert fetched is not None
    assert fetched.status == "completed"


@pytest.mark.asyncio
async def test_delete_document(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    doc_id = doc.id

    deleted = await delete_document(db_session, doc_id)
    assert deleted is True

    fetched = await get_document(db_session, doc_id)
    assert fetched is None


@pytest.mark.asyncio
async def test_create_job(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)

    job = await create_job(
        db_session,
        document_id=doc.id,
        job_type="text_extraction",
        status="pending",
    )
    assert job.id is not None
    assert job.document_id == doc.id
    assert job.job_type == "text_extraction"
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_get_jobs_for_document(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)

    await create_job(
        db_session,
        document_id=doc.id,
        job_type="text_extraction",
        status="pending",
    )
    await create_job(
        db_session,
        document_id=doc.id,
        job_type="ocr",
        status="running",
    )

    jobs = await get_jobs_for_document(db_session, doc.id)
    assert len(jobs) == 2
    job_types = {j.job_type for j in jobs}
    assert job_types == {"text_extraction", "ocr"}
