from fastapi import APIRouter

from backend.database.engine import AsyncSessionLocal  # noqa: F401 (patched in tests)

router = APIRouter(prefix="/api/chat", tags=["chat"])
