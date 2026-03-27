from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CorrectionCreate(BaseModel):
    field_path: str    # "anchor.total_amount" | "lines"
    new_value: str     # always string; caller serialises Decimal/list to string


class LockRequest(BaseModel):
    field_path: str
    is_locked: bool


class FieldCorrectionResponse(BaseModel):
    id: str
    extraction_id: str
    field_path: str
    old_value: str | None
    new_value: str
    corrected_at: datetime
    is_locked: bool
    model_config = {"from_attributes": True}


class CorrectionsListResponse(BaseModel):
    extraction_id: str
    corrections: list[FieldCorrectionResponse]  # latest per field
    locked_fields: list[str]


class ReextractFieldResponse(BaseModel):
    field: str
    proposed_value: str | None
    confidence: str    # "high" | "medium" | "low" | "failed"
    message: str | None = None
