from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, field_validator


class TemplateField(BaseModel):
    field_path: str
    display_name: str
    include: bool = True


class ExportTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    fields: list[TemplateField]


class ExportTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    fields: list[TemplateField] | None = None


class ExportTemplateResponse(BaseModel):
    id: str
    name: str
    description: str | None
    fields: list[TemplateField]
    created_at: datetime
    updated_at: datetime

    @field_validator("fields", mode="before")
    @classmethod
    def parse_fields(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    model_config = {"from_attributes": True}
