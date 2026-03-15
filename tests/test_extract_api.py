# tests/test_extract_api.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from backend.schemas.invoice import Invoice, InvoiceLine, InvoiceType
from backend.services.invoice_validator import ValidationResult


def _make_invoice() -> Invoice:
    line = InvoiceLine(
        line_number=1,
        description="Srv",
        base_amount=Decimal("100.00"),
        iva_rate=Decimal("21"),
        iva_amount=Decimal("21.00"),
        total_line=Decimal("121.00"),
    )
    return Invoice(
        invoice_type=InvoiceType.STANDARD,
        invoice_number="F-001",
        issue_date=date(2026, 3, 15),
        issuer_name="Acme SL",
        issuer_cif="A12345679",
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


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    import fitz

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Factura número 001 NIF CIF IVA Total")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


async def _upload_pdf(client: AsyncClient, pdf_path: Path) -> str:
    with open(pdf_path, "rb") as f:
        resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", f, "application/pdf")},
        )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_trigger_extraction_not_found(client: AsyncClient):
    resp = await client.post("/api/extract/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_extraction_creates_job(client: AsyncClient, sample_pdf: Path):
    doc_id = await _upload_pdf(client, sample_pdf)

    with patch("backend.api.extract._run_extraction", new_callable=AsyncMock):
        resp = await client.post(f"/api/extract/{doc_id}")

    assert resp.status_code == 201
    data = resp.json()
    assert data["job_type"] == "extraction"
    assert data["status"] == "pending"
    assert data["document_id"] == doc_id


@pytest.mark.asyncio
async def test_trigger_extraction_409_duplicate(client: AsyncClient, sample_pdf: Path):
    doc_id = await _upload_pdf(client, sample_pdf)

    with patch("backend.api.extract._run_extraction", new_callable=AsyncMock):
        resp1 = await client.post(f"/api/extract/{doc_id}")
        assert resp1.status_code == 201
        resp2 = await client.post(f"/api/extract/{doc_id}")
        assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_get_extraction_not_found(client: AsyncClient):
    resp = await client.get("/api/extract/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_extraction_not_started(client: AsyncClient, sample_pdf: Path):
    doc_id = await _upload_pdf(client, sample_pdf)
    resp = await client.get(f"/api/extract/{doc_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_status"] == "not_started"
    assert data["extraction_status"] is None
    assert data["invoice_json_available"] is False


@pytest.mark.asyncio
async def test_get_extraction_after_trigger(client: AsyncClient, sample_pdf: Path, tmp_path: Path):
    doc_id = await _upload_pdf(client, sample_pdf)

    # Write a fake JSON file for the invoice
    invoice = _make_invoice()
    json_path = tmp_path / f"{doc_id}.json"
    json_path.write_text(invoice.model_dump_json())

    # Simulate a completed extraction in DB using the patched AsyncSessionLocal
    # Import inside the test body so we get the already-patched module reference
    import backend.database.engine as engine_module
    from backend.database.crud import create_extraction, create_job, update_job

    async with engine_module.AsyncSessionLocal() as db:
        job = await create_job(db, document_id=doc_id, job_type="extraction", status="completed")
        await create_extraction(db, doc_id, invoice, ValidationResult(True, [], False), str(json_path))

    resp = await client.get(f"/api/extract/{doc_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_status"] == "completed"
    assert data["extraction_status"] == "valid"
    assert data["invoice_json_available"] is True
    assert data["invoice"] is not None
