from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.database.models import Base
from backend.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    # Patch AsyncSessionLocal so background tasks use the test DB
    import backend.api.chat as chat_module
    import backend.api.documents as docs_module
    import backend.api.export as export_module
    import backend.api.extract as extract_module
    import backend.api.ocr as ocr_module
    import backend.database.engine as engine_module

    orig_session_local = engine_module.AsyncSessionLocal
    engine_module.AsyncSessionLocal = session_factory
    docs_module.AsyncSessionLocal = session_factory
    ocr_module.AsyncSessionLocal = session_factory
    extract_module.AsyncSessionLocal = session_factory
    chat_module.AsyncSessionLocal = session_factory
    export_module.AsyncSessionLocal = session_factory

    async with session_factory() as session:
        yield session

    engine_module.AsyncSessionLocal = orig_session_local
    docs_module.AsyncSessionLocal = orig_session_local
    ocr_module.AsyncSessionLocal = orig_session_local
    extract_module.AsyncSessionLocal = orig_session_local
    chat_module.AsyncSessionLocal = orig_session_local
    export_module.AsyncSessionLocal = orig_session_local
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, tmp_path: Path) -> AsyncGenerator[AsyncClient, None]:
    # Override settings to use a temp directory so uploads don't go to real data/
    temp_settings = Settings(DATA_DIR=tmp_path)
    temp_settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    get_settings.cache_clear()

    # Patch get_settings used inside the upload endpoint
    from backend import config as config_module

    config_module.get_settings.cache_clear()

    # Temporarily override the function
    import backend.config as backend_config
    import backend.utils.file_utils as file_utils_module

    _orig = backend_config.get_settings

    def _patched_settings() -> Settings:
        return temp_settings

    # Monkeypatch the cached function
    backend_config.get_settings = _patched_settings  # type: ignore[assignment]
    file_utils_module.get_settings = _patched_settings  # type: ignore[assignment]

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides = {}
        backend_config.get_settings = _orig
        file_utils_module.get_settings = _orig
        _orig.cache_clear()


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    import fitz  # PyMuPDF

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello World test document")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    import cv2
    import numpy as np

    img = np.zeros((100, 200, 3), dtype=np.uint8)
    cv2.putText(img, "Test", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    img_path = tmp_path / "test_image.png"
    cv2.imwrite(str(img_path), img)
    return img_path


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    temp_settings = Settings(DATA_DIR=tmp_path)
    temp_settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

    import backend.config as backend_config

    backend_config.get_settings.cache_clear()
    monkeypatch.setattr(backend_config, "get_settings", lambda: temp_settings)

    return tmp_path
