from __future__ import annotations

import copy
import json
from typing import Any

from backend.database.crud import (
    create_correction,
    delete_corrections_for_field,
    get_latest_corrections,
    set_correction_lock,
)
from backend.database.models import Extraction, FieldCorrection


def _get_nested(d: dict, path: str) -> Any:
    """Navigate dict with dot notation. 'anchor.total_amount' → d['anchor']['total_amount'].
    Returns None if path not found."""
    parts = path.split(".")
    current = d
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _set_nested(d: dict, path: str, value: Any) -> None:
    """Set value at dot-path in dict (mutates in place). Creates missing intermediate dicts."""
    parts = path.split(".")
    current = d
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def apply_corrections_to_dict(raw: dict, corrections: dict[str, Any]) -> dict:
    """
    Pure function. Deep-copies raw, overlays corrections by field_path.
    - "anchor.*" paths: navigate raw["anchor"][field]
    - "lines" special case: sets raw["discovered"]["line_items"] = json.loads(correction.new_value)
    Returns the corrected dict. Original `raw` is NOT mutated.
    """
    result = copy.deepcopy(raw)
    for field_path, correction in corrections.items():
        if field_path == "lines":
            if "discovered" not in result:
                result["discovered"] = {}
            try:
                result["discovered"]["line_items"] = json.loads(correction.new_value)
            except (json.JSONDecodeError, ValueError):
                # Malformed JSON in correction — skip silently (preserve existing value)
                pass
        else:
            _set_nested(result, field_path, correction.new_value)
    return result


async def get_corrected_extraction_result(db, extraction: Extraction):
    """
    Main entry point for export/display.
    Reads extraction.json_path, applies corrections, returns ExtractionResult.
    Import ExtractionResult locally to avoid circular imports.
    """
    from backend.schemas.extraction import ExtractionResult

    try:
        with open(extraction.json_path) as f:
            raw = json.load(f)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"Extraction JSON file not found: {extraction.json_path}") from exc

    corrections = await get_latest_corrections(db, extraction.id)
    corrected = apply_corrections_to_dict(raw, corrections)
    return ExtractionResult.from_dict(corrected)


async def save_correction(
    db,
    extraction_id: str,
    field_path: str,
    new_value: str,
    current_raw: dict,
) -> FieldCorrection:
    """Resolves old_value from current_raw, inserts FieldCorrection row."""
    old_value = _get_nested(current_raw, field_path)
    if old_value is not None:
        old_value = str(old_value)
    return await create_correction(db, extraction_id, field_path, old_value, new_value)


async def set_field_lock(
    db,
    extraction_id: str,
    field_path: str,
    is_locked: bool,
    current_raw: dict,
) -> FieldCorrection:
    """
    Updates is_locked on the latest correction.
    If no correction exists, creates a sentinel (old_value == new_value == current value).
    """
    corrections = await get_latest_corrections(db, extraction_id)
    if field_path in corrections:
        return await set_correction_lock(db, corrections[field_path].id, is_locked)
    else:
        # Create sentinel: no actual change, just a lock marker
        current_value = _get_nested(current_raw, field_path)
        value_str = str(current_value) if current_value is not None else ""
        return await create_correction(
            db, extraction_id, field_path, value_str, value_str, is_locked=is_locked
        )


async def reset_field(db, extraction_id: str, field_path: str) -> None:
    """Deletes all FieldCorrection rows for (extraction_id, field_path)."""
    await delete_corrections_for_field(db, extraction_id, field_path)


def is_field_locked(corrections: dict[str, Any], field_path: str) -> bool:
    """Returns True if the latest correction for field_path has is_locked=True."""
    correction = corrections.get(field_path)
    return correction is not None and correction.is_locked
