from __future__ import annotations

import json
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.crud import (
    delete_corrections_for_field,  # noqa: F401
    get_latest_corrections,
)
from backend.database.engine import AsyncSessionLocal, get_db  # noqa: F401
from backend.database.models import Extraction
from backend.schemas.corrections import (
    CorrectionCreate,
    CorrectionsListResponse,
    FieldCorrectionResponse,
    LockRequest,
)
from backend.services.correction_service import (
    apply_corrections_to_dict,
    reset_field,
    save_correction,
    set_field_lock,
)

router = APIRouter(prefix="/api/corrections", tags=["corrections"])


async def _get_extraction(db: AsyncSession, document_id: str) -> Extraction:
    """Fetch extraction by document_id or raise 404."""
    result = await db.execute(
        select(Extraction).where(Extraction.document_id == document_id)
    )
    extraction = result.scalar_one_or_none()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return extraction


async def _load_corrected_dict(db: AsyncSession, extraction: Extraction) -> dict:
    """Read raw JSON from disk and overlay current corrections."""
    try:
        with open(extraction.json_path) as f:
            raw = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Extraction data file missing or corrupt: {exc}",
        ) from exc
    corrections = await get_latest_corrections(db, extraction.id)
    return apply_corrections_to_dict(raw, corrections)


@router.get("/{document_id}", response_model=CorrectionsListResponse)
async def get_corrections(document_id: str, db: AsyncSession = Depends(get_db)):
    extraction = await _get_extraction(db, document_id)

    corrections = await get_latest_corrections(db, extraction.id)
    locked_fields = [fp for fp, c in corrections.items() if c.is_locked]

    return CorrectionsListResponse(
        extraction_id=extraction.id,
        corrections=list(corrections.values()),
        locked_fields=locked_fields,
    )


@router.post("/{document_id}", response_model=FieldCorrectionResponse, status_code=201)
async def create_correction(
    document_id: str, body: CorrectionCreate, db: AsyncSession = Depends(get_db)
):
    extraction = await _get_extraction(db, document_id)
    current_dict = await _load_corrected_dict(db, extraction)
    correction = await save_correction(
        db, extraction.id, body.field_path, body.new_value, current_dict
    )
    return correction


@router.post("/{document_id}/lock", response_model=FieldCorrectionResponse)
async def lock_correction(
    document_id: str, body: LockRequest, db: AsyncSession = Depends(get_db)
):
    extraction = await _get_extraction(db, document_id)
    current_dict = await _load_corrected_dict(db, extraction)
    correction = await set_field_lock(
        db, extraction.id, body.field_path, body.is_locked, current_dict
    )
    return correction


@router.delete("/{document_id}/{field_path:path}", status_code=204)
async def delete_correction(
    document_id: str, field_path: str, db: AsyncSession = Depends(get_db)
):
    extraction = await _get_extraction(db, document_id)
    await reset_field(db, extraction.id, unquote(field_path))
