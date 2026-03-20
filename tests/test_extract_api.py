# tests/test_extract_api.py
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import dataclasses
import json
import pytest
from httpx import AsyncClient

from backend.schemas.extraction import AnchorFields, ExtractionIssue, ExtractionResult


def _make_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        anchor=AnchorFields(
            invoice_number="F-001", issue_date="2026-03-01",
            issuer_name="Acme SL", issuer_cif="A12345679",
            recipient_name="Client SA", recipient_cif="12345678Z",
            base_imponible=Decimal("100.00"), iva_rate=Decimal("21"),
            iva_amount=Decimal("21.00"), total_amount=Decimal("121.00"),
            currency="EUR",
        ),
        discovered={}, issues=[], requires_review=False,
        llm_model="qwen3.5:9b", extraction_timestamp="2026-03-20T10:00:00Z",
    )


def _result_to_json(result: ExtractionResult) -> str:
    def _default(obj):
        if isinstance(obj, Decimal): return str(obj)
        raise TypeError
    return json.dumps(dataclasses.asdict(result), default=_default, indent=2)


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

    result = _make_extraction_result()
    json_path = tmp_path / f"{doc_id}.json"
    json_path.write_text(_result_to_json(result))

    import backend.database.engine as engine_module
    from backend.database.crud import create_extraction, create_job

    async with engine_module.AsyncSessionLocal() as db:
        await create_job(db, document_id=doc_id, job_type="extraction", status="completed")
        await create_extraction(db, doc_id, result, str(json_path))

    resp = await client.get(f"/api/extract/{doc_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_status"] == "completed"
    assert data["extraction_status"] == "valid"
    assert data["invoice_json_available"] is True
    assert data["invoice"] is not None
    assert data["invoice"]["anchor"]["invoice_number"] == "F-001"


@pytest.mark.asyncio
async def test_export_md_returns_markdown(client: AsyncClient, sample_pdf: Path, tmp_path: Path):
    doc_id = await _upload_pdf(client, sample_pdf)
    result = _make_extraction_result()
    json_path = tmp_path / f"{doc_id}.json"
    json_path.write_text(_result_to_json(result))

    import backend.database.engine as engine_module
    from backend.database.crud import create_extraction, create_job

    async with engine_module.AsyncSessionLocal() as db:
        await create_job(db, document_id=doc_id, job_type="extraction", status="completed")
        await create_extraction(db, doc_id, result, str(json_path))

    resp = await client.get(f"/api/extract/{doc_id}/export?format=md")
    assert resp.status_code == 200
    assert "F-001" in resp.text
    assert resp.headers["content-type"].startswith("text/markdown")


@pytest.mark.asyncio
async def test_export_csv_returns_csv(client: AsyncClient, sample_pdf: Path, tmp_path: Path):
    doc_id = await _upload_pdf(client, sample_pdf)
    result = _make_extraction_result()
    json_path = tmp_path / f"{doc_id}.json"
    json_path.write_text(_result_to_json(result))

    import backend.database.engine as engine_module
    from backend.database.crud import create_extraction, create_job

    async with engine_module.AsyncSessionLocal() as db:
        await create_job(db, document_id=doc_id, job_type="extraction", status="completed")
        await create_extraction(db, doc_id, result, str(json_path))

    resp = await client.get(f"/api/extract/{doc_id}/export?format=csv")
    assert resp.status_code == 200
    assert "invoice_number" in resp.text
    assert "F-001" in resp.text
    assert resp.headers["content-type"].startswith("text/csv")


@pytest.mark.asyncio
async def test_export_404_when_no_extraction(client: AsyncClient, sample_pdf: Path):
    doc_id = await _upload_pdf(client, sample_pdf)
    resp = await client.get(f"/api/extract/{doc_id}/export?format=md")
    assert resp.status_code == 404
