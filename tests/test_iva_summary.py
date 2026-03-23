"""Tests for IVA summary aggregation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Document, Extraction
from backend.services.iva_summary import compute_iva_summary


def _write_extraction_json(tmp_path: Path, doc_id: str, anchor: dict) -> str:
    """Write a minimal extraction JSON file and return its path."""
    data = {
        "anchor": anchor,
        "discovered": {},
        "issues": [],
        "requires_review": False,
        "llm_model": "test",
        "extraction_timestamp": "2024-01-01T00:00:00",
    }
    path = tmp_path / f"{doc_id}.json"
    path.write_text(json.dumps(data))
    return str(path)


async def _add_extraction(db: AsyncSession, doc_id: str, issue_date: str, json_path: str):
    # Create a stub Document row first to satisfy the FK constraint
    doc = Document(
        id=doc_id,
        filename=f"{doc_id}.pdf",
        format=".pdf",
        file_path=f"/tmp/{doc_id}.pdf",
        file_size=1024,
    )
    db.add(doc)
    await db.flush()

    ext = Extraction(
        id=doc_id,
        document_id=doc_id,
        issue_date=issue_date,
        total_amount="1210.00",
        status="valid",
        json_path=json_path,
    )
    db.add(ext)
    await db.commit()


@pytest.mark.asyncio
async def test_iva_summary_empty(db_session: AsyncSession, tmp_path: Path):
    result = await compute_iva_summary(db_session, None, None)
    assert result["rates"] == []
    assert result["totals"]["invoice_count"] == 0
    assert result["totals"]["iva_total"] == "0.00"


@pytest.mark.asyncio
async def test_iva_summary_single_rate(db_session: AsyncSession, tmp_path: Path):
    json_path = _write_extraction_json(tmp_path, "doc1", {
        "base_imponible": "1000.00",
        "iva_rate": "21",
        "iva_amount": "210.00",
        "irpf_amount": None,
    })
    await _add_extraction(db_session, "doc1", "2024-01-15", json_path)

    result = await compute_iva_summary(db_session, None, None)
    assert len(result["rates"]) == 1
    assert result["rates"][0]["iva_rate"] == "21.00"
    assert result["rates"][0]["base_imponible_total"] == "1000.00"
    assert result["rates"][0]["iva_total"] == "210.00"
    assert result["totals"]["invoice_count"] == 1


@pytest.mark.asyncio
async def test_iva_summary_multiple_rates(db_session: AsyncSession, tmp_path: Path):
    json_path_1 = _write_extraction_json(tmp_path, "doc1", {
        "base_imponible": "1000.00", "iva_rate": "21", "iva_amount": "210.00",
    })
    json_path_2 = _write_extraction_json(tmp_path, "doc2", {
        "base_imponible": "500.00", "iva_rate": "10", "iva_amount": "50.00",
    })
    await _add_extraction(db_session, "doc1", "2024-01-15", json_path_1)
    await _add_extraction(db_session, "doc2", "2024-01-20", json_path_2)

    result = await compute_iva_summary(db_session, None, None)
    assert len(result["rates"]) == 2
    assert result["totals"]["invoice_count"] == 2


@pytest.mark.asyncio
async def test_iva_summary_date_filter_from(db_session: AsyncSession, tmp_path: Path):
    json_path_1 = _write_extraction_json(tmp_path, "doc1", {
        "base_imponible": "1000.00", "iva_rate": "21", "iva_amount": "210.00",
    })
    json_path_2 = _write_extraction_json(tmp_path, "doc2", {
        "base_imponible": "500.00", "iva_rate": "21", "iva_amount": "105.00",
    })
    await _add_extraction(db_session, "doc1", "2024-01-15", json_path_1)  # before filter
    await _add_extraction(db_session, "doc2", "2024-03-01", json_path_2)  # after filter

    result = await compute_iva_summary(db_session, date_from="2024-02-01", date_to=None)
    assert result["totals"]["invoice_count"] == 1


@pytest.mark.asyncio
async def test_iva_summary_date_filter_to(db_session: AsyncSession, tmp_path: Path):
    json_path_1 = _write_extraction_json(tmp_path, "doc1", {
        "base_imponible": "1000.00", "iva_rate": "21", "iva_amount": "210.00",
    })
    json_path_2 = _write_extraction_json(tmp_path, "doc2", {
        "base_imponible": "500.00", "iva_rate": "21", "iva_amount": "105.00",
    })
    await _add_extraction(db_session, "doc1", "2024-01-15", json_path_1)
    await _add_extraction(db_session, "doc2", "2024-03-01", json_path_2)

    result = await compute_iva_summary(db_session, date_from=None, date_to="2024-02-01")
    assert result["totals"]["invoice_count"] == 1


@pytest.mark.asyncio
async def test_iva_summary_both_date_filters(db_session: AsyncSession, tmp_path: Path):
    json_path_1 = _write_extraction_json(
        tmp_path, "doc1", {"iva_rate": "21", "base_imponible": "100.00", "iva_amount": "21.00"}
    )
    json_path_2 = _write_extraction_json(
        tmp_path, "doc2", {"iva_rate": "21", "base_imponible": "200.00", "iva_amount": "42.00"}
    )
    json_path_3 = _write_extraction_json(
        tmp_path, "doc3", {"iva_rate": "21", "base_imponible": "300.00", "iva_amount": "63.00"}
    )
    await _add_extraction(db_session, "doc1", "2024-01-01", json_path_1)
    await _add_extraction(db_session, "doc2", "2024-02-15", json_path_2)
    await _add_extraction(db_session, "doc3", "2024-04-01", json_path_3)

    result = await compute_iva_summary(db_session, date_from="2024-02-01", date_to="2024-03-31")
    assert result["totals"]["invoice_count"] == 1


@pytest.mark.asyncio
async def test_iva_summary_missing_json(db_session: AsyncSession, tmp_path: Path):
    """If JSON file doesn't exist, that row is skipped, no crash."""
    await _add_extraction(db_session, "doc1", "2024-01-15", "/nonexistent/path/doc1.json")

    result = await compute_iva_summary(db_session, None, None)
    # Should not raise, invoice is silently skipped
    assert result["totals"]["invoice_count"] == 0


@pytest.mark.asyncio
async def test_iva_summary_irpf_totals(db_session: AsyncSession, tmp_path: Path):
    """IRPF amounts are correctly summed across invoices."""
    json_path_1 = _write_extraction_json(tmp_path, "doc1", {
        "base_imponible": "1000.00", "iva_rate": "21", "iva_amount": "210.00",
        "irpf_amount": "150.00",
    })
    json_path_2 = _write_extraction_json(tmp_path, "doc2", {
        "base_imponible": "500.00", "iva_rate": "21", "iva_amount": "105.00",
        "irpf_amount": "75.00",
    })
    await _add_extraction(db_session, "doc1", "2024-01-15", json_path_1)
    await _add_extraction(db_session, "doc2", "2024-01-20", json_path_2)

    result = await compute_iva_summary(db_session, None, None)
    assert result["totals"]["irpf_total"] == "225.00"


@pytest.mark.asyncio
async def test_csv_includes_irpf_in_total_row(db_session: AsyncSession, tmp_path: Path):
    """CSV TOTAL row must have 5 columns; column index 3 (0-based) is the IRPF amount."""
    import csv as _csv
    from io import StringIO
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    json_path = _write_extraction_json(tmp_path, "doc1", {
        "base_imponible": "1000.00",
        "iva_rate": "21",
        "iva_amount": "210.00",
        "irpf_amount": "150.00",
    })
    await _add_extraction(db_session, "doc1", "2024-01-15", json_path)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[__import__("backend.database.engine", fromlist=["get_db"]).get_db] = _override_get_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/export/iva-summary/csv")
        assert response.status_code == 200
        rows = list(_csv.reader(StringIO(response.text)))
        total_row = next(r for r in rows if r and r[0] == "TOTAL")
        assert len(total_row) == 5, f"TOTAL row should have 5 columns, got {len(total_row)}: {total_row}"
        assert total_row[3] == "150.00", f"Column 3 (IRPF) should be '150.00', got '{total_row[3]}'"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_csv_endpoint_includes_irpf_in_total_row(db_session: AsyncSession, tmp_path: Path):
    """The actual CSV endpoint response has 5 columns in TOTAL row with IRPF amount."""
    import csv as _csv
    from io import StringIO
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    json_path = _write_extraction_json(tmp_path, "doc1", {
        "base_imponible": "2000.00",
        "iva_rate": "21",
        "iva_amount": "420.00",
        "irpf_amount": "300.00",
    })
    await _add_extraction(db_session, "doc1", "2024-01-15", json_path)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[__import__("backend.database.engine", fromlist=["get_db"]).get_db] = _override_get_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/export/iva-summary/csv")
        assert response.status_code == 200
        rows = list(_csv.reader(StringIO(response.text)))
        total_row = next(r for r in rows if r and r[0] == "TOTAL")
        assert len(total_row) == 5, f"TOTAL row should have 5 columns, got: {total_row}"
        assert total_row[3] == "300.00", f"IRPF column should be '300.00', got '{total_row[3]}'"
        # Also check header has IRPF column
        header_row = rows[0]
        assert header_row[3] == "IRPF Retenido", f"Header col 3 should be 'IRPF Retenido', got '{header_row[3]}'"
    finally:
        app.dependency_overrides.clear()
