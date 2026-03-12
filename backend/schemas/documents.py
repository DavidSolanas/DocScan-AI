from datetime import datetime

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    format: str
    file_size: int
    status: str
    upload_date: datetime

    model_config = {"from_attributes": True}


class DocumentDetail(BaseModel):
    id: str
    filename: str
    format: str
    file_path: str
    file_size: int
    page_count: int | None
    status: str
    text_content: str | None
    is_scanned: bool | None
    ocr_confidence: float | None = None
    upload_date: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentDetail]
    total: int


class DocumentTextResponse(BaseModel):
    id: str
    filename: str
    text_content: str | None
    page_count: int | None
    is_scanned: bool | None
    ocr_confidence: float | None = None

    model_config = {"from_attributes": True}
