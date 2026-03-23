from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.schemas.corrections import (
    CorrectionCreate,
    FieldCorrectionResponse,
)
from backend.schemas.templates import (
    ExportTemplateResponse,
    ExportTemplateUpdate,
    TemplateField,
)


def test_correction_create_validates_field_path():
    obj = CorrectionCreate(field_path="anchor.total", new_value="100")
    assert obj.field_path == "anchor.total"
    assert obj.new_value == "100"


def test_field_correction_response_from_orm():
    class FakeOrm:
        id = "corr-1"
        extraction_id = "extr-1"
        field_path = "anchor.total_amount"
        old_value = "99.00"
        new_value = "100.00"
        corrected_at = datetime(2026, 3, 23, 10, 0, 0, tzinfo=timezone.utc)
        is_locked = False

    result = FieldCorrectionResponse.model_validate(FakeOrm())
    assert result.id == "corr-1"
    assert result.extraction_id == "extr-1"
    assert result.field_path == "anchor.total_amount"
    assert result.old_value == "99.00"
    assert result.new_value == "100.00"
    assert result.is_locked is False


def test_export_template_response_parses_fields_json():
    fields_json = '[{"field_path":"anchor.total_amount","display_name":"Total","include":true}]'
    now = datetime(2026, 3, 23, 10, 0, 0, tzinfo=timezone.utc)
    response = ExportTemplateResponse(
        id="tmpl-1",
        name="My Template",
        description=None,
        fields=fields_json,
        created_at=now,
        updated_at=now,
    )
    assert isinstance(response.fields, list)
    assert len(response.fields) == 1
    assert isinstance(response.fields[0], TemplateField)
    assert response.fields[0].field_path == "anchor.total_amount"
    assert response.fields[0].display_name == "Total"
    assert response.fields[0].include is True


def test_export_template_update_all_optional():
    obj = ExportTemplateUpdate()
    assert obj.name is None
    assert obj.description is None
    assert obj.fields is None
