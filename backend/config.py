from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATA_DIR: Path = Path("data")

    @property
    def DOCUMENTS_DIR(self) -> Path:
        return self.DATA_DIR / "documents"

    @property
    def THUMBNAILS_DIR(self) -> Path:
        return self.DATA_DIR / "thumbnails"

    @property
    def EXTRACTIONS_DIR(self) -> Path:
        return self.DATA_DIR / "extractions"

    @property
    def EXPORTS_DIR(self) -> Path:
        return self.DATA_DIR / "exports"

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/docscanai.db"

    ALLOWED_EXTENSIONS: set[str] = {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".webp",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".odt",
        ".ods",
        ".eml",
        ".msg",
        ".zip",
        ".rar",
    }

    MAX_UPLOAD_SIZE_MB: int = 100

    TESSERACT_LANG: str = "spa+eng"
    TESSERACT_PSM: int = 3
    OCR_TARGET_DPI: int = 300
    OCR_CONFIDENCE_THRESHOLD: float = 70.0
    PREPROCESSING_ENABLED: bool = True
    GLM_OCR_ENABLED: bool = True
    GLM_OCR_MODEL: str = "glm-ocr"
    LAYOUT_DETECTION_ENABLED: bool = True
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_DEFAULT_MODEL: str = "qwen3.5:9b"
    OLLAMA_TIMEOUT: int = 300        # seconds per Ollama call
    LLM_MAX_RETRIES: int = 2
    TABLE_EXTRACTION_ENABLED: bool = True
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"
    RAG_CHUNK_SIZE: int = 2000
    RAG_CHUNK_OVERLAP: int = 100
    RAG_TOP_K: int = 5
    RAG_MAX_CHUNKS: int = 50
    CHAT_MAX_HISTORY_MESSAGES: int = 6
    RAG_ENABLED: bool = True

    @property
    def CHROMA_DIR(self) -> Path:
        return self.DATA_DIR / "chroma"

    model_config = {"env_prefix": "DOCSCAN_"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_directories() -> None:
    settings = get_settings()
    for directory in (
        settings.DOCUMENTS_DIR,
        settings.THUMBNAILS_DIR,
        settings.EXTRACTIONS_DIR,
        settings.EXPORTS_DIR,
        settings.CHROMA_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
