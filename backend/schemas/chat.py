from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, field_validator


class ChatSessionCreate(BaseModel):
    document_id: str | None = None
    document_id_b: str | None = None
    mode: str = "single"
    title: str | None = None


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    citations: list[dict] | None = None
    created_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def parse_citations(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return None
        return v

    model_config = {"from_attributes": True}


class ChatSessionResponse(BaseModel):
    id: str
    document_id: str | None = None
    document_id_b: str | None = None
    mode: str
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageResponse] = []

    model_config = {"from_attributes": True}
