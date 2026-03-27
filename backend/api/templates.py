from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.crud import (
    create_template,
    delete_template,
    get_template,
    get_template_by_name,
    list_templates,
    update_template,
)
from backend.database.engine import AsyncSessionLocal, get_db  # noqa: F401
from backend.database.models import ExportTemplate
from backend.schemas.templates import (
    ExportTemplateCreate,
    ExportTemplateResponse,
    ExportTemplateUpdate,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _to_response(tmpl: ExportTemplate) -> ExportTemplateResponse:
    """Convert ORM ExportTemplate to response schema.

    The ORM stores fields as ``fields_json`` (a JSON string), while the
    Pydantic schema exposes them as ``fields`` (a list).  We pass the raw
    JSON string via the ``fields`` key so the schema's ``parse_fields``
    validator can deserialise it.
    """
    return ExportTemplateResponse.model_validate(
        {
            "id": tmpl.id,
            "name": tmpl.name,
            "description": tmpl.description,
            "fields": tmpl.fields_json,  # validator handles str → list
            "created_at": tmpl.created_at,
            "updated_at": tmpl.updated_at,
        }
    )


@router.get("", response_model=list[ExportTemplateResponse])
async def list_all_templates(db: AsyncSession = Depends(get_db)):
    templates = await list_templates(db)
    return [_to_response(t) for t in templates]


@router.post("", response_model=ExportTemplateResponse, status_code=201)
async def create_new_template(
    body: ExportTemplateCreate, db: AsyncSession = Depends(get_db)
):
    existing = await get_template_by_name(db, body.name)
    if existing is not None:
        raise HTTPException(status_code=409, detail="A template with that name already exists")

    fields_json = json.dumps([f.model_dump() for f in body.fields])
    tmpl = await create_template(db, name=body.name, description=body.description, fields_json=fields_json)
    return _to_response(tmpl)


@router.get("/{template_id}", response_model=ExportTemplateResponse)
async def get_template_by_id(template_id: str, db: AsyncSession = Depends(get_db)):
    tmpl = await get_template(db, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return _to_response(tmpl)


@router.put("/{template_id}", response_model=ExportTemplateResponse)
async def update_template_by_id(
    template_id: str, body: ExportTemplateUpdate, db: AsyncSession = Depends(get_db)
):
    tmpl = await get_template(db, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    kwargs: dict = {}
    if body.name is not None:
        kwargs["name"] = body.name
    if body.description is not None:
        kwargs["description"] = body.description
    if body.fields is not None:
        kwargs["fields_json"] = json.dumps([f.model_dump() for f in body.fields])

    if not kwargs:
        return _to_response(tmpl)

    updated = await update_template(db, template_id, **kwargs)
    if updated is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return _to_response(updated)


@router.delete("/{template_id}", status_code=204)
async def delete_template_by_id(template_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await delete_template(db, template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
