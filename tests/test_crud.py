from __future__ import annotations

import json
from datetime import date
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
from backend.schemas.invoice import Invoice, InvoiceLine, InvoiceType
from backend.services.invoice_validator import ValidationResult


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


def _make_invoice_for_crud(
    invoice_number: str = "F-001",
    issuer_cif: str = "A12345679",
    invoice_series: str | None = None,
) -> Invoice:
    line = InvoiceLine(
        line_number=1, description="Srv",
        base_amount=Decimal("100.00"), iva_rate=Decimal("21"),
        iva_amount=Decimal("21.00"), total_line=Decimal("121.00"),
    )
    return Invoice(
        invoice_type=InvoiceType.STANDARD,
        invoice_number=invoice_number,
        invoice_series=invoice_series,
        issue_date=date(2026, 3, 15),
        issuer_name="Acme SL",
        issuer_cif=issuer_cif,
        issuer_address="Calle Mayor 1",
        recipient_name="Client SA",
        recipient_cif="12345678Z",
        lines=[line],
        tax_breakdown=[],
        subtotal=Decimal("100.00"),
        total_iva=Decimal("21.00"),
        total_amount=Decimal("121.00"),
        source_file="test.pdf",
        extraction_confidence=0.9,
    )


def _make_valid_result() -> ValidationResult:
    return ValidationResult(valid=True, issues=[], requires_manual_review=False)


@pytest.mark.asyncio
async def test_create_extraction(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    invoice = _make_invoice_for_crud()
    result = _make_valid_result()

    extraction = await create_extraction(db_session, doc.id, invoice, result, "/tmp/ext.json")
    assert extraction.id is not None
    assert extraction.document_id == doc.id
    assert extraction.invoice_number == "F-001"
    assert extraction.issuer_cif == "A12345679"
    assert extraction.status == "valid"


@pytest.mark.asyncio
async def test_get_extraction_by_document_id_found(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    invoice = _make_invoice_for_crud()
    await create_extraction(db_session, doc.id, invoice, _make_valid_result(), "/tmp/ext.json")

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
    invoice = _make_invoice_for_crud(invoice_number="F-001", issuer_cif="A12345679")
    await create_extraction(db_session, doc.id, invoice, _make_valid_result(), "/tmp/ext.json")

    dup = await find_duplicate(db_session, "A12345679", "F-001", None)
    assert dup is not None


@pytest.mark.asyncio
async def test_find_duplicate_no_match(db_session: AsyncSession) -> None:
    result = await find_duplicate(db_session, "A12345679", "F-999", None)
    assert result is None


@pytest.mark.asyncio
async def test_upsert_extraction_creates_when_not_exists(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    invoice = _make_invoice_for_crud()
    extraction = await upsert_extraction(db_session, doc.id, invoice, _make_valid_result(), "/tmp/ext.json")
    assert extraction.id is not None


@pytest.mark.asyncio
async def test_upsert_extraction_updates_when_exists(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session)
    invoice = _make_invoice_for_crud(invoice_number="F-001")

    first = await upsert_extraction(db_session, doc.id, invoice, _make_valid_result(), "/tmp/v1.json")
    invoice2 = _make_invoice_for_crud(invoice_number="F-002")
    second = await upsert_extraction(db_session, doc.id, invoice2, _make_valid_result(), "/tmp/v2.json")

    assert first.id == second.id  # same row, updated
    assert second.invoice_number == "F-002"
    assert second.json_path == "/tmp/v2.json"
