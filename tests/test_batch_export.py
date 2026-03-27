from __future__ import annotations
import io, json, zipfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.database import crud
from datetime import datetime, timezone

async def _make_doc_with_extraction(db, doc_id, filename, json_data):
    """Helper: create a document + extraction + write json_path file."""
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.write(json.dumps(json_data).encode())
    tmp.close()
    await crud.create_document(db, id=doc_id, filename=filename,
        format=".pdf", file_path=f"/tmp/{filename}", file_size=100, status="completed",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    await crud.create_extraction(db, doc_id,
        result={"invoice_number": "001", "issuer_name": "SA", "issuer_cif": "B12345678",
                "recipient_name": "SL", "recipient_cif": "A87654321",
                "issue_date": "2025-03-01", "total_amount": "100.00",
                "invoice_type": "STANDARD", "status": "valid", "validation_errors": []},
        json_path=tmp.name)
    return tmp.name

@pytest.mark.asyncio
async def test_batch_export_json_returns_zip(client, db_session):
    tmp = await _make_doc_with_extraction(db_session, "d1", "factura.pdf",
                                          {"invoice_number": "001"})
    await db_session.commit()
    resp = await client.post("/api/batch/export",
                              json={"document_ids": ["d1"], "format": "json"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert any(n.endswith(".json") for n in zf.namelist())

@pytest.mark.asyncio
async def test_batch_export_empty_ids_returns_400(client, db_session):
    resp = await client.post("/api/batch/export",
                              json={"document_ids": [], "format": "json"})
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_batch_export_over_50_returns_400(client, db_session):
    resp = await client.post("/api/batch/export",
                              json={"document_ids": [str(i) for i in range(51)],
                                    "format": "json"})
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_batch_export_unknown_doc_returns_404(client, db_session):
    resp = await client.post("/api/batch/export",
                              json={"document_ids": ["nonexistent"], "format": "json"})
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_batch_export_all_no_extraction_returns_400(client, db_session):
    await crud.create_document(db_session, id="d1", filename="f.pdf",
        format=".pdf", file_path="/tmp/f.pdf", file_size=100, status="uploaded",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    await db_session.commit()
    resp = await client.post("/api/batch/export",
                              json={"document_ids": ["d1"], "format": "json"})
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_batch_export_invalid_format_returns_400(client, db_session):
    resp = await client.post("/api/batch/export",
                              json={"document_ids": ["d1"], "format": "sii"})
    assert resp.status_code == 400
