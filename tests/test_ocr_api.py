"""Tests for OCR API endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    import fitz

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello World test document")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.mark.asyncio
async def test_trigger_ocr_not_found(client: AsyncClient):
    resp = await client.post("/api/ocr/nonexistent", json={"lang": "eng"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_ocr_creates_job(client: AsyncClient, sample_pdf: Path):
    # Upload a document first
    with open(sample_pdf, "rb") as f:
        upload_resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", f, "application/pdf")},
        )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # Patch the background task to not actually run OCR
    with patch("backend.api.ocr.ocr_document_task", new_callable=AsyncMock):
        resp = await client.post(f"/api/ocr/{doc_id}", json={"lang": "eng", "preprocess": True})
    assert resp.status_code == 201
    data = resp.json()
    assert data["job_type"] == "ocr"
    assert data["status"] == "pending"
    assert data["document_id"] == doc_id


@pytest.mark.asyncio
async def test_trigger_ocr_409_duplicate(client: AsyncClient, sample_pdf: Path):
    with open(sample_pdf, "rb") as f:
        upload_resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", f, "application/pdf")},
        )
    doc_id = upload_resp.json()["id"]

    with patch("backend.api.ocr.ocr_document_task", new_callable=AsyncMock):
        resp1 = await client.post(f"/api/ocr/{doc_id}")
        assert resp1.status_code == 201

        resp2 = await client.post(f"/api/ocr/{doc_id}")
        assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_get_ocr_result_not_found(client: AsyncClient):
    resp = await client.get("/api/ocr/nonexistent/result")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_ocr_result_no_results(client: AsyncClient, sample_pdf: Path):
    with open(sample_pdf, "rb") as f:
        upload_resp = await client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", f, "application/pdf")},
        )
    doc_id = upload_resp.json()["id"]

    resp = await client.get(f"/api/ocr/{doc_id}/result")
    assert resp.status_code == 404
    assert "No OCR results" in resp.json()["detail"]
