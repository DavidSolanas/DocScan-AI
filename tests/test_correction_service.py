from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.crud import create_document, create_extraction
from backend.schemas.extraction import AnchorFields, ExtractionResult
from backend.services.correction_service import (
    _get_nested,
    _set_nested,
    apply_corrections_to_dict,
    is_field_locked,
    reset_field,
    save_correction,
    set_field_lock,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        anchor=AnchorFields(
            invoice_number="F-001",
            issuer_cif="A12345679",
            issuer_name="Test SL",
            recipient_cif="12345678Z",
            recipient_name="Client SA",
            issue_date="2026-03-01",
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


async def _make_extraction(db: AsyncSession):
    doc = await create_document(
        db,
        filename="test.pdf",
        format=".pdf",
        file_path="/tmp/test.pdf",
        file_size=1024,
    )
    extraction = await create_extraction(db, doc.id, _make_extraction_result(), "/tmp/ext.json")
    return extraction


def _make_correction_stub(new_value: str, is_locked: bool = False):
    """Create a lightweight mock that mimics a FieldCorrection ORM row."""
    from types import SimpleNamespace
    return SimpleNamespace(new_value=new_value, is_locked=is_locked)


# ---------------------------------------------------------------------------
# 1. test_get_nested_simple
# ---------------------------------------------------------------------------


def test_get_nested_simple():
    d = {"anchor": {"total": "100"}}
    assert _get_nested(d, "anchor.total") == "100"


# ---------------------------------------------------------------------------
# 2. test_get_nested_missing
# ---------------------------------------------------------------------------


def test_get_nested_missing():
    assert _get_nested({}, "anchor.total") is None


# ---------------------------------------------------------------------------
# 3. test_set_nested_creates_path
# ---------------------------------------------------------------------------


def test_set_nested_creates_path():
    d = {}
    _set_nested(d, "anchor.x", "v")
    assert d["anchor"]["x"] == "v"


# ---------------------------------------------------------------------------
# 4. test_set_nested_overwrites
# ---------------------------------------------------------------------------


def test_set_nested_overwrites():
    d = {"anchor": {"x": "old"}}
    _set_nested(d, "anchor.x", "new")
    assert d["anchor"]["x"] == "new"


# ---------------------------------------------------------------------------
# 5. test_apply_corrections_anchor_field
# ---------------------------------------------------------------------------


def test_apply_corrections_anchor_field():
    raw = {
        "anchor": {"issuer_name": "Original SL", "total_amount": "100.00"},
        "discovered": {},
        "issues": [],
        "requires_review": False,
        "llm_model": "test",
        "extraction_timestamp": "2026-01-01T00:00:00Z",
    }
    stub = _make_correction_stub("Corrected SL")
    corrections = {"anchor.issuer_name": stub}

    result = apply_corrections_to_dict(raw, corrections)

    assert result["anchor"]["issuer_name"] == "Corrected SL"
    # Original unchanged
    assert raw["anchor"]["issuer_name"] == "Original SL"


# ---------------------------------------------------------------------------
# 6. test_apply_corrections_lines_field
# ---------------------------------------------------------------------------


def test_apply_corrections_lines_field():
    raw = {
        "anchor": {},
        "discovered": {},
        "issues": [],
        "requires_review": False,
        "llm_model": "test",
        "extraction_timestamp": "2026-01-01T00:00:00Z",
    }
    line_items = [{"description": "Widget", "quantity": 2, "unit_price": "10.00", "total": "20.00"}]
    stub = _make_correction_stub(json.dumps(line_items))
    corrections = {"lines": stub}

    result = apply_corrections_to_dict(raw, corrections)

    assert result["discovered"]["line_items"] == line_items


# ---------------------------------------------------------------------------
# 7. test_apply_corrections_no_mutations
# ---------------------------------------------------------------------------


def test_apply_corrections_no_mutations():
    raw = {
        "anchor": {"issuer_name": "Original SL"},
        "discovered": {},
        "issues": [],
        "requires_review": False,
        "llm_model": "test",
        "extraction_timestamp": "2026-01-01T00:00:00Z",
    }
    original_raw_copy = json.loads(json.dumps(raw))
    stub = _make_correction_stub("Changed SL")
    corrections = {"anchor.issuer_name": stub}

    apply_corrections_to_dict(raw, corrections)

    # raw must be identical to what it was before
    assert raw == original_raw_copy


# ---------------------------------------------------------------------------
# 8. test_save_correction_captures_old_value  (DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_correction_captures_old_value(db_session: AsyncSession):
    extraction = await _make_extraction(db_session)

    current_raw = {
        "anchor": {"issuer_name": "Old Name SL"},
    }

    correction = await save_correction(
        db_session,
        extraction_id=extraction.id,
        field_path="anchor.issuer_name",
        new_value="New Name SL",
        current_raw=current_raw,
    )

    assert correction.old_value == "Old Name SL"
    assert correction.new_value == "New Name SL"
    assert correction.field_path == "anchor.issuer_name"


# ---------------------------------------------------------------------------
# 9. test_set_field_lock_creates_sentinel  (DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_field_lock_creates_sentinel(db_session: AsyncSession):
    extraction = await _make_extraction(db_session)

    current_raw = {
        "anchor": {"total_amount": "121.00"},
    }

    # No prior correction exists — should create a sentinel
    sentinel = await set_field_lock(
        db_session,
        extraction_id=extraction.id,
        field_path="anchor.total_amount",
        is_locked=True,
        current_raw=current_raw,
    )

    assert sentinel is not None
    assert sentinel.is_locked is True
    # Sentinel: old_value == new_value == current value
    assert sentinel.old_value == "121.00"
    assert sentinel.new_value == "121.00"
    assert sentinel.field_path == "anchor.total_amount"


# ---------------------------------------------------------------------------
# 10. test_is_field_locked
# ---------------------------------------------------------------------------


def test_is_field_locked():
    locked_stub = _make_correction_stub("val", is_locked=True)
    unlocked_stub = _make_correction_stub("val", is_locked=False)

    corrections_with_lock = {"anchor.total_amount": locked_stub}
    corrections_without_lock = {"anchor.total_amount": unlocked_stub}
    empty_corrections = {}

    assert is_field_locked(corrections_with_lock, "anchor.total_amount") is True
    assert is_field_locked(corrections_without_lock, "anchor.total_amount") is False
    assert is_field_locked(empty_corrections, "anchor.total_amount") is False
