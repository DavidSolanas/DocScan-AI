from __future__ import annotations
import pytest
from httpx import AsyncClient
from backend.database import crud

@pytest.mark.asyncio
async def test_filter_returns_all_without_params(client, db_session):
    await crud.create_document(db_session, id="doc1", filename="factura.pdf",
        format=".pdf", file_path="/tmp/f.pdf", file_size=100, status="completed",
        upload_date=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc))
    await db_session.commit()
    resp = await client.get("/api/documents/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["documents"][0]["id"] == "doc1"

@pytest.mark.asyncio
async def test_filter_by_filename(client, db_session):
    await crud.create_document(db_session, id="d1", filename="factura_001.pdf",
        format=".pdf", file_path="/tmp/a.pdf", file_size=100, status="completed",
        upload_date=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc))
    await crud.create_document(db_session, id="d2", filename="recibo.pdf",
        format=".pdf", file_path="/tmp/b.pdf", file_size=100, status="completed",
        upload_date=__import__("datetime").datetime(2025, 3, 2, tzinfo=__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime(2025, 3, 2, tzinfo=__import__("datetime").timezone.utc))
    await db_session.commit()
    resp = await client.get("/api/documents/?q=factura")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["documents"][0]["filename"] == "factura_001.pdf"

@pytest.mark.asyncio
async def test_filter_by_vendor(client, db_session):
    from backend.services.intelligent_extractor import IntelligentExtractor
    doc = await crud.create_document(db_session, id="d1", filename="f.pdf",
        format=".pdf", file_path="/tmp/f.pdf", file_size=100, status="completed",
        upload_date=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc))
    await crud.create_extraction(db_session, "d1",
        result={"invoice_number": "001", "issuer_name": "Empresa SA",
                "issuer_cif": "B12345678", "recipient_name": "Cliente SL",
                "recipient_cif": "A87654321", "issue_date": "2025-03-01",
                "total_amount": "1200.00", "invoice_type": "STANDARD",
                "status": "valid", "validation_errors": []},
        json_path="/tmp/e.json")
    await db_session.commit()
    resp = await client.get("/api/documents/?vendor=Empresa")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["documents"][0]["issuer_name"] == "Empresa SA"

@pytest.mark.asyncio
async def test_filter_by_status(client, db_session):
    await crud.create_document(db_session, id="d1", filename="a.pdf",
        format=".pdf", file_path="/tmp/a.pdf", file_size=100, status="completed",
        upload_date=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc))
    await crud.create_document(db_session, id="d2", filename="b.pdf",
        format=".pdf", file_path="/tmp/b.pdf", file_size=100, status="uploaded",
        upload_date=__import__("datetime").datetime(2025, 3, 2, tzinfo=__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime(2025, 3, 2, tzinfo=__import__("datetime").timezone.utc))
    await db_session.commit()
    resp = await client.get("/api/documents/?status=uploaded")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["documents"][0]["id"] == "d2"

@pytest.mark.asyncio
async def test_filter_by_date_range(client, db_session):
    await crud.create_document(db_session, id="d1", filename="a.pdf",
        format=".pdf", file_path="/tmp/a.pdf", file_size=100, status="completed",
        upload_date=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc))
    await crud.create_extraction(db_session, "d1",
        result={"invoice_number": "001", "issuer_name": "SA", "issuer_cif": "B12345678",
                "recipient_name": "SL", "recipient_cif": "A87654321",
                "issue_date": "2025-03-01", "total_amount": "100.00",
                "invoice_type": "STANDARD", "status": "valid", "validation_errors": []},
        json_path="/tmp/e.json")
    await db_session.commit()
    resp = await client.get("/api/documents/?date_from=01/02/2025&date_to=30/04/2025")
    data = resp.json()
    assert data["total"] == 1
    resp2 = await client.get("/api/documents/?date_from=01/04/2025")
    assert resp2.json()["total"] == 0

@pytest.mark.asyncio
async def test_filter_by_amount_range(client, db_session):
    await crud.create_document(db_session, id="d1", filename="a.pdf",
        format=".pdf", file_path="/tmp/a.pdf", file_size=100, status="completed",
        upload_date=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc))
    await crud.create_extraction(db_session, "d1",
        result={"invoice_number": "001", "issuer_name": "SA", "issuer_cif": "B12345678",
                "recipient_name": "SL", "recipient_cif": "A87654321",
                "issue_date": "2025-03-01", "total_amount": "1200.00",
                "invoice_type": "STANDARD", "status": "valid", "validation_errors": []},
        json_path="/tmp/e.json")
    await db_session.commit()
    resp = await client.get("/api/documents/?amount_min=1000&amount_max=2000")
    assert resp.json()["total"] == 1
    resp2 = await client.get("/api/documents/?amount_min=2000")
    assert resp2.json()["total"] == 0

@pytest.mark.asyncio
async def test_sort_by_filename_asc(client, db_session):
    for name in ["z_invoice.pdf", "a_invoice.pdf", "m_invoice.pdf"]:
        await crud.create_document(db_session, id=name[:1], filename=name,
            format=".pdf", file_path=f"/tmp/{name}", file_size=100, status="completed",
            upload_date=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc),
            updated_at=__import__("datetime").datetime(2025, 3, 1, tzinfo=__import__("datetime").timezone.utc))
    await db_session.commit()
    resp = await client.get("/api/documents/?sort_by=filename&sort_order=asc")
    filenames = [d["filename"] for d in resp.json()["documents"]]
    assert filenames == sorted(filenames)

@pytest.mark.asyncio
async def test_pagination_total_reflects_filter(client, db_session):
    for i in range(5):
        await crud.create_document(db_session, id=f"d{i}", filename=f"factura_{i}.pdf",
            format=".pdf", file_path=f"/tmp/f{i}.pdf", file_size=100, status="completed",
            upload_date=__import__("datetime").datetime(2025, 3, i+1, tzinfo=__import__("datetime").timezone.utc),
            updated_at=__import__("datetime").datetime(2025, 3, i+1, tzinfo=__import__("datetime").timezone.utc))
    await db_session.commit()
    resp = await client.get("/api/documents/?q=factura&skip=0&limit=2")
    data = resp.json()
    assert data["total"] == 5      # total filtered count
    assert len(data["documents"]) == 2  # only page 1
