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
    ):
        directory.mkdir(parents=True, exist_ok=True)
