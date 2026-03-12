from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient


async def _upload_pdf(client: AsyncClient, pdf_path: Path) -> dict:
    with pdf_path.open("rb") as f:
        response = await client.post(
            "/api/documents/upload",
            files={"file": (pdf_path.name, f, "application/pdf")},
        )
    return response


@pytest.mark.asyncio
async def test_upload_pdf(client: AsyncClient, sample_pdf: Path) -> None:
    response = await _upload_pdf(client, sample_pdf)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert "filename" in data
    assert "status" in data
    assert data["filename"] == sample_pdf.name


@pytest.mark.asyncio
async def test_upload_invalid_format(client: AsyncClient, tmp_path: Path) -> None:
    exe_file = tmp_path / "malware.exe"
    exe_file.write_bytes(b"MZ\x90\x00")

    with exe_file.open("rb") as f:
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("malware.exe", f, "application/octet-stream")},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_documents(client: AsyncClient, sample_pdf: Path) -> None:
    # Upload a document first
    upload_response = await _upload_pdf(client, sample_pdf)
    assert upload_response.status_code == 201

    list_response = await client.get("/api/documents/")
    assert list_response.status_code == 200
    data = list_response.json()
    assert "documents" in data
    assert "total" in data
    assert data["total"] >= 1
    filenames = [d["filename"] for d in data["documents"]]
    assert sample_pdf.name in filenames


@pytest.mark.asyncio
async def test_get_document(client: AsyncClient, sample_pdf: Path) -> None:
    upload_response = await _upload_pdf(client, sample_pdf)
    assert upload_response.status_code == 201
    doc_id = upload_response.json()["id"]

    get_response = await client.get(f"/api/documents/{doc_id}")
    assert get_response.status_code == 200
    data = get_response.json()
    assert data["id"] == doc_id
    assert data["filename"] == sample_pdf.name
    assert "status" in data
    assert "file_size" in data


@pytest.mark.asyncio
async def test_get_document_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/documents/nonexistent-id-000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_document(client: AsyncClient, sample_pdf: Path) -> None:
    upload_response = await _upload_pdf(client, sample_pdf)
    assert upload_response.status_code == 201
    doc_id = upload_response.json()["id"]

    delete_response = await client.delete(f"/api/documents/{doc_id}")
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/documents/{doc_id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_get_file(client: AsyncClient, sample_pdf: Path) -> None:
    upload_response = await _upload_pdf(client, sample_pdf)
    assert upload_response.status_code == 201
    doc_id = upload_response.json()["id"]

    file_response = await client.get(f"/api/documents/{doc_id}/file")
    assert file_response.status_code == 200
    assert "application/pdf" in file_response.headers.get("content-type", "")
