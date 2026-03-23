from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import crud
from backend.database.engine import (  # noqa: F401 (AsyncSessionLocal patched in tests)
    AsyncSessionLocal,
    get_db,
)
from backend.schemas.chat import ChatMessageResponse, ChatSessionCreate, ChatSessionResponse
from backend.services.chat_service import ChatService
from backend.services.llm_service import get_llm_service
from backend.services.rag_service import RagService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class SendMessageRequest(BaseModel):
    question: str


def _get_chat_service() -> ChatService:
    llm = get_llm_service()
    rag = RagService()
    return ChatService(rag_service=rag, llm_service=llm)


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
async def create_session(
    body: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
):
    session = await crud.create_session(
        db,
        document_id=body.document_id,
        document_id_b=body.document_id_b,
        mode=body.mode,
        title=body.title,
    )
    # Reload with messages (eager load)
    session = await crud.get_session(db, session.id)
    return ChatSessionResponse.model_validate(session)


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    document_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    sessions = await crud.list_sessions(db, document_id=document_id)
    return [ChatSessionResponse.model_validate(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = await crud.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return ChatSessionResponse.model_validate(session)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    deleted = await crud.delete_session(db, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse, status_code=201)
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    session = await crud.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build history from existing messages
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in session.messages
    ]
    settings = get_settings()
    max_hist = settings.CHAT_MAX_HISTORY_MESSAGES
    history = history[-max_hist:]

    # Store user message
    await crud.create_message(db, session_id=session_id, role="user", content=body.question)

    # Get answer from ChatService
    chat_svc = _get_chat_service()
    try:
        answer, citations = await chat_svc.answer(
            question=body.question,
            document_id=session.document_id or "",
            history=history,
            document_id_b=session.document_id_b,
        )
    except Exception as exc:
        logger.exception("ChatService.answer failed for session %s", session_id)
        answer = f"Error generating answer: {exc}"
        citations = []

    # Store assistant message
    citations_json = json.dumps(citations) if citations else None
    msg = await crud.create_message(
        db, session_id=session_id, role="assistant", content=answer, citations=citations_json
    )
    return ChatMessageResponse.model_validate(msg)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def list_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = await crud.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await crud.list_messages(db, session_id)
    return [ChatMessageResponse.model_validate(m) for m in messages]


@router.post("/index/{document_id}")
async def index_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    import json as _json

    from sqlalchemy import select

    from backend.database.models import Job
    from backend.schemas.extraction import ExtractionResult

    doc = await crud.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.text_content:
        raise HTTPException(status_code=422, detail="Document has no text content — run OCR first")

    extraction = await crud.get_extraction_by_document_id(db, document_id)
    extraction_result = None
    if extraction is not None:
        try:
            raw = _json.loads(Path(extraction.json_path).read_text())
            extraction_result = ExtractionResult.from_dict(raw)
        except Exception:
            pass

    # Try to extract page-level texts from the latest completed OCR job
    ocr_job_result = await db.execute(
        select(Job)
        .where(
            Job.document_id == document_id,
            Job.job_type == "ocr",
            Job.status == "completed",
        )
        .order_by(Job.completed_at.desc())
        .limit(1)
    )
    ocr_job = ocr_job_result.scalar_one_or_none()

    page_texts: list[str] | None = None
    if ocr_job and ocr_job.result:
        try:
            result_data = _json.loads(ocr_job.result)
            # Job.result for OCR stores {"pages": [{"page_number": 1, "text": "...", ...}]}
            pages = result_data.get("pages") or []
            page_texts = [p.get("text") or "" for p in pages]
        except Exception:
            pass

    rag = RagService()
    chunks_indexed = await rag.index_document(
        document_id=document_id,
        text=doc.text_content,
        extraction_result=extraction_result,
        page_texts=page_texts,
    )
    return {"chunks_indexed": chunks_indexed}
