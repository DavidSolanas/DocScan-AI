"""OCR-related Pydantic schemas."""

from pydantic import BaseModel


class OCRTriggerRequest(BaseModel):
    lang: str = "spa+eng"
    preprocess: bool = True


class OCRPageSchema(BaseModel):
    page_number: int
    text: str
    average_confidence: float
    low_confidence: bool
    word_count: int


class OCRResultResponse(BaseModel):
    document_id: str
    full_text: str
    average_confidence: float
    page_count: int
    low_confidence_pages: list[int]
    pages: list[OCRPageSchema]
