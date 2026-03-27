from __future__ import annotations

import io
import json as _json
import os
import zipfile
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import crud
from backend.database.engine import AsyncSessionLocal, get_db  # noqa: F401

router = APIRouter(prefix="/api/batch", tags=["batch"])


class BatchExportRequest(BaseModel):
    document_ids: List[str]
    format: str  # "xlsx" | "csv" | "json"


@router.post("/export")
async def batch_export(
    request: BatchExportRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="No document IDs provided")
    if len(request.document_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 documents per batch export")
    if request.format not in ("xlsx", "csv", "json"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{request.format}'. Use xlsx, csv, or json",
        )

    zip_buffer = io.BytesIO()
    skipped = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc_id in request.document_ids:
            doc = await crud.get_document(db, doc_id)
            if doc is None:
                raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")

            ext = await crud.get_extraction_by_document_id(db, doc_id)
            if ext is None:
                skipped += 1
                continue

            stem = doc.filename.rsplit(".", 1)[0]

            if request.format == "json":
                # Raw extraction JSON from disk
                if ext.json_path and os.path.exists(ext.json_path):
                    with open(ext.json_path, "rb") as f:
                        content = f.read()
                    zf.writestr(f"{stem}.json", content)
                else:
                    skipped += 1
                    continue
            elif request.format == "csv":
                from backend.services.correction_service import get_corrected_extraction_result
                from backend.services.extractor_export import to_csv
                result = await get_corrected_extraction_result(db, ext)
                content = to_csv(result)
                zf.writestr(
                    f"{stem}.csv",
                    content.encode("utf-8") if isinstance(content, str) else content,
                )
            elif request.format == "xlsx":
                from backend.services.correction_service import get_corrected_extraction_result
                from backend.services.excel_exporter import to_xlsx
                result = await get_corrected_extraction_result(db, ext)
                content = to_xlsx(result, doc.filename)
                zf.writestr(f"{stem}.xlsx", content)

    if skipped == len(request.document_ids):
        raise HTTPException(
            status_code=400,
            detail="No documents with completed extractions found in the selection",
        )

    zip_buffer.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"docscanai_export_{ts}.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
