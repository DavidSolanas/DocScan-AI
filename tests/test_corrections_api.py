# tests/test_corrections_api.py
from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient

from backend.schemas.extraction import AnchorFields, ExtractionResult


def _make_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        anchor=AnchorFields(
            invoice_number="F-001",
            issue_date="2026-03-01",
            issuer_name="Acme SL",
            issuer_cif="A12345679",
            recipient_name="Client SA",
            recipient_cif="12345678Z",
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


def _result_to_json(result: ExtractionResult) -> str:
    def _default(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError

    return json.dumps(dataclasses.asdict(result), default=_default, indent=2)


async def _create_extraction_fixture(tmp_path: Path, doc_id: str) -> str:
    """Creates a JSON file for an extraction result and returns the path."""
    result = _make_extraction_result()
    json_path = tmp_path / f"{doc_id}.json"
    json_path.write_text(_result_to_json(result))
    return str(json_path)


@pytest.mark.asyncio
async def test_get_corrections_not_found(client: AsyncClient):
    """404 when no extraction exists for document_id."""
    resp = await client.get("/api/corrections/nonexistent-doc")
    assert resp.status_code == 404
    assert "Extraction not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_corrections_empty(client: AsyncClient, tmp_path: Path):
    """Extraction exists with no corrections → empty list."""
    import backend.database.engine as engine_module
    from backend.database.crud import create_document, create_extraction

    result = _make_extraction_result()
    async with engine_module.AsyncSessionLocal() as db:
        doc = await create_document(
            db,
            filename="test.pdf",
            format="pdf",
            file_path="/tmp/test.pdf",
            file_size=1234,
        )
        json_path = await _create_extraction_fixture(tmp_path, doc.id)
        await create_extraction(db, doc.id, result, json_path)

    resp = await client.get(f"/api/corrections/{doc.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["corrections"] == []
    assert data["locked_fields"] == []


@pytest.mark.asyncio
async def test_post_correction_creates_record(client: AsyncClient, tmp_path: Path):
    """POST creates a correction, returns 201 with the new FieldCorrectionResponse."""
    import backend.database.engine as engine_module
    from backend.database.crud import create_document, create_extraction

    result = _make_extraction_result()
    async with engine_module.AsyncSessionLocal() as db:
        doc = await create_document(
            db,
            filename="test.pdf",
            format="pdf",
            file_path="/tmp/test.pdf",
            file_size=1234,
        )
        json_path = await _create_extraction_fixture(tmp_path, doc.id)
        await create_extraction(db, doc.id, result, json_path)

    payload = {"field_path": "anchor.total_amount", "new_value": "150.00"}
    resp = await client.post(f"/api/corrections/{doc.id}", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["field_path"] == "anchor.total_amount"
    assert data["new_value"] == "150.00"
    assert data["is_locked"] is False

    # Verify correction now appears in GET
    resp2 = await client.get(f"/api/corrections/{doc.id}")
    assert resp2.status_code == 200
    corrections = resp2.json()["corrections"]
    assert len(corrections) == 1
    assert corrections[0]["field_path"] == "anchor.total_amount"


@pytest.mark.asyncio
async def test_post_correction_extraction_not_found(client: AsyncClient):
    """404 when POST correction for non-existent document."""
    payload = {"field_path": "anchor.total_amount", "new_value": "99.00"}
    resp = await client.post("/api/corrections/no-such-doc", json=payload)
    assert resp.status_code == 404
    assert "Extraction not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_lock_correction(client: AsyncClient, tmp_path: Path):
    """POST /lock sets is_locked=True on an existing correction."""
    import backend.database.engine as engine_module
    from backend.database.crud import create_document, create_extraction

    result = _make_extraction_result()
    async with engine_module.AsyncSessionLocal() as db:
        doc = await create_document(
            db,
            filename="test.pdf",
            format="pdf",
            file_path="/tmp/test.pdf",
            file_size=1234,
        )
        json_path = await _create_extraction_fixture(tmp_path, doc.id)
        await create_extraction(db, doc.id, result, json_path)

    # First create a correction
    await client.post(
        f"/api/corrections/{doc.id}",
        json={"field_path": "anchor.invoice_number", "new_value": "F-999"},
    )

    # Now lock it
    resp = await client.post(
        f"/api/corrections/{doc.id}/lock",
        json={"field_path": "anchor.invoice_number", "is_locked": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_locked"] is True
    assert data["field_path"] == "anchor.invoice_number"


@pytest.mark.asyncio
async def test_lock_creates_sentinel_when_no_correction(client: AsyncClient, tmp_path: Path):
    """Locking a field that has no correction creates a sentinel row."""
    import backend.database.engine as engine_module
    from backend.database.crud import create_document, create_extraction

    result = _make_extraction_result()
    async with engine_module.AsyncSessionLocal() as db:
        doc = await create_document(
            db,
            filename="test.pdf",
            format="pdf",
            file_path="/tmp/test.pdf",
            file_size=1234,
        )
        json_path = await _create_extraction_fixture(tmp_path, doc.id)
        await create_extraction(db, doc.id, result, json_path)

    # Lock a field that has never been corrected
    resp = await client.post(
        f"/api/corrections/{doc.id}/lock",
        json={"field_path": "anchor.issuer_cif", "is_locked": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_locked"] is True
    assert data["field_path"] == "anchor.issuer_cif"
    # Sentinel: old_value == new_value (the current extracted value)
    assert data["old_value"] == data["new_value"]


@pytest.mark.asyncio
async def test_delete_correction(client: AsyncClient, tmp_path: Path):
    """DELETE /corrections/{doc_id}/{field_path} returns 204, corrections list becomes empty."""
    import backend.database.engine as engine_module
    from backend.database.crud import create_document, create_extraction

    result = _make_extraction_result()
    async with engine_module.AsyncSessionLocal() as db:
        doc = await create_document(
            db,
            filename="test.pdf",
            format="pdf",
            file_path="/tmp/test.pdf",
            file_size=1234,
        )
        json_path = await _create_extraction_fixture(tmp_path, doc.id)
        await create_extraction(db, doc.id, result, json_path)

    # Create a correction
    await client.post(
        f"/api/corrections/{doc.id}",
        json={"field_path": "anchor.total_amount", "new_value": "200.00"},
    )

    # Confirm it exists
    resp = await client.get(f"/api/corrections/{doc.id}")
    assert len(resp.json()["corrections"]) == 1

    # Delete it
    resp = await client.delete(f"/api/corrections/{doc.id}/anchor.total_amount")
    assert resp.status_code == 204

    # Confirm it's gone
    resp = await client.get(f"/api/corrections/{doc.id}")
    assert resp.json()["corrections"] == []


@pytest.mark.asyncio
async def test_get_corrections_returns_locked_fields(client: AsyncClient, tmp_path: Path):
    """Locked corrections appear in the locked_fields list."""
    import backend.database.engine as engine_module
    from backend.database.crud import create_document, create_extraction

    result = _make_extraction_result()
    async with engine_module.AsyncSessionLocal() as db:
        doc = await create_document(
            db,
            filename="test.pdf",
            format="pdf",
            file_path="/tmp/test.pdf",
            file_size=1234,
        )
        json_path = await _create_extraction_fixture(tmp_path, doc.id)
        await create_extraction(db, doc.id, result, json_path)

    # Create and lock a correction
    await client.post(
        f"/api/corrections/{doc.id}",
        json={"field_path": "anchor.issuer_name", "new_value": "Updated SL"},
    )
    await client.post(
        f"/api/corrections/{doc.id}/lock",
        json={"field_path": "anchor.issuer_name", "is_locked": True},
    )

    resp = await client.get(f"/api/corrections/{doc.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "anchor.issuer_name" in data["locked_fields"]
    # Also verify the correction has is_locked=True
    correction = next(c for c in data["corrections"] if c["field_path"] == "anchor.issuer_name")
    assert correction["is_locked"] is True
