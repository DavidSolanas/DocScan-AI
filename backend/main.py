from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.documents import router as documents_router
from backend.api.jobs import router as jobs_router
from backend.api.ocr import router as ocr_router
from backend.config import ensure_directories
from backend.database.engine import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_directories()
    await init_db()
    yield


app = FastAPI(
    title="DocScan AI",
    description="Local-first document scanning, OCR, and structured extraction.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(jobs_router)
app.include_router(ocr_router)

# StaticFiles mount must come last so API routes take priority
_frontend_dir = Path(__file__).parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
