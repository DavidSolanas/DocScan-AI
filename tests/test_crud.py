from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.crud import (
    create_document,
    create_extraction,
    create_job,
    delete_document,
    find_duplicate,
    get_document,
    get_extraction_by_document_id,
    get_jobs_for_document,
    list_documents,
    update_document,
    upsert_extraction,
)
from backend.schemas.extraction import AnchorFields, ExtractionIssue, ExtractionResult


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


# --- Extraction CRUD tests ---


def _make_extraction_result(invoice_number="F-001", issuer_cif="A12345679") -> ExtractionResult:
    return ExtractionResult(
        anchor=AnchorFields(
            invoice_number=invoice_number,
            issuer_cif=issuer_cif,
            issuer_name="Test SL",
            recipient_cif="12345678Z",
            recipient_name="Client SA",
            issue_date="2026-03-01",
            base_imponible=Decimal("100.00"),
            iva_rate=Decimal("21"),
            iva_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            currency="EUR",
        ),
        discovered={},
        issues=[],
        requires_review=False,
        llm_model="qwen3.5:9b",
        extraction_timestamp="2026-03-20T10:00:00Z",
    )


# --- Extraction CRUD tests ---

@pytest.mark.asyncio
async def test_create_extraction(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    result = _make_extraction_result()
    extraction = await create_extraction(db_session, doc.id, result, "/tmp/ext.json")
    assert extraction.id is not None
    assert extraction.document_id == doc.id
    assert extraction.invoice_number == "F-001"
    assert extraction.issuer_cif == "A12345679"
    assert extraction.status == "valid"


@pytest.mark.asyncio
async def test_get_extraction_by_document_id_found(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    await create_extraction(db_session, doc.id, _make_extraction_result(), "/tmp/ext.json")
    found = await get_extraction_by_document_id(db_session, doc.id)
    assert found is not None
    assert found.document_id == doc.id


@pytest.mark.asyncio
async def test_get_extraction_by_document_id_not_found(db_session: AsyncSession) -> None:
    result = await get_extraction_by_document_id(db_session, "nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_find_duplicate_exact_match(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    await create_extraction(db_session, doc.id, _make_extraction_result(invoice_number="F-001", issuer_cif="A12345679"), "/tmp/ext.json")
    dup = await find_duplicate(db_session, "A12345679", "F-001")
    assert dup is not None


@pytest.mark.asyncio
async def test_find_duplicate_no_match(db_session: AsyncSession) -> None:
    result = await find_duplicate(db_session, "A12345679", "F-999")
    assert result is None


@pytest.mark.asyncio
async def test_upsert_extraction_creates_when_not_exists(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    extraction = await upsert_extraction(db_session, doc.id, _make_extraction_result(), "/tmp/ext.json")
    assert extraction.id is not None


@pytest.mark.asyncio
async def test_upsert_extraction_updates_when_exists(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    first = await upsert_extraction(db_session, doc.id, _make_extraction_result(invoice_number="F-001"), "/tmp/v1.json")
    second = await upsert_extraction(db_session, doc.id, _make_extraction_result(invoice_number="F-002"), "/tmp/v2.json")
    assert first.id == second.id  # same row, updated
    assert second.invoice_number == "F-002"
    assert second.json_path == "/tmp/v2.json"
