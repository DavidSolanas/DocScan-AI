from __future__ import annotations
import io, json, zipfile
import pytest
from backend.config import get_settings
from backend.database import crud
from datetime import datetime, timezone

async def _make_doc_with_extraction(db, doc_id, filename, json_data, json_path=None):
    """Helper: create a document + extraction + write json_path file inside EXTRACTIONS_DIR."""
    settings = get_settings()
    settings.EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    if json_path is None:
        json_path = settings.EXTRACTIONS_DIR / f"{doc_id}.json"
    json_path = json_path if hasattr(json_path, "write_text") else __import__("pathlib").Path(json_path)
    json_path.write_text(json.dumps(json_data))
    await crud.create_document(db, id=doc_id, filename=filename,
        format=".pdf", file_path=f"/tmp/{filename}", file_size=100, status="completed",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    await crud.create_extraction(db, doc_id,
        result={"invoice_number": "001", "issuer_name": "SA", "issuer_cif": "B12345678",
                "recipient_name": "SL", "recipient_cif": "A87654321",
                "issue_date": "2025-03-01", "total_amount": "100.00",
                "invoice_type": "STANDARD", "status": "valid", "validation_errors": []},
        json_path=str(json_path))
    return json_path

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

@pytest.mark.asyncio
async def test_batch_export_path_traversal_returns_400(client, db_session):
    """json_path pointing outside EXTRACTIONS_DIR must be rejected."""
    import pathlib
    outside_path = pathlib.Path("/tmp/evil.json")
    outside_path.write_text(json.dumps({"secret": "data"}))
    await crud.create_document(db_session, id="evil", filename="evil.pdf",
        format=".pdf", file_path="/tmp/evil.pdf", file_size=100, status="completed",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    await crud.create_extraction(db_session, "evil",
        result={"invoice_number": "X", "issuer_name": "X", "issuer_cif": "X",
                "recipient_name": "X", "recipient_cif": "X",
                "issue_date": "2025-03-01", "total_amount": "0",
                "invoice_type": "STANDARD", "status": "valid", "validation_errors": []},
        json_path=str(outside_path))
    await db_session.commit()
    resp = await client.post("/api/batch/export",
                              json={"document_ids": ["evil"], "format": "json"})
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_batch_export_skipped_count_header(client, db_session):
    """X-Skipped-Count header reports how many docs had no extraction."""
    await _make_doc_with_extraction(db_session, "d1", "factura.pdf", {"invoice_number": "001"})
    # d2 has no extraction
    await crud.create_document(db_session, id="d2", filename="no_ext.pdf",
        format=".pdf", file_path="/tmp/no_ext.pdf", file_size=100, status="uploaded",
        upload_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    await db_session.commit()
    resp = await client.post("/api/batch/export",
                              json={"document_ids": ["d1", "d2"], "format": "csv"})
    assert resp.status_code == 200
    assert resp.headers.get("x-skipped-count") == "1"
