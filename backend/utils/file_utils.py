from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from backend.config import Settings, get_settings


def validate_extension(filename: str) -> bool:
    """Return True if the file's extension is in the configured allowed set."""
    settings = get_settings()
    suffix = Path(filename).suffix.lower()
    return suffix in settings.ALLOWED_EXTENSIONS


def save_upload(upload_file: UploadFile, settings: Settings) -> tuple[Path, int]:
    """Save an uploaded file under a UUID subdirectory of DOCUMENTS_DIR.

    Returns a (file_path, file_size) tuple.
    """
    subdir = settings.DOCUMENTS_DIR / str(uuid.uuid4())
    subdir.mkdir(parents=True, exist_ok=True)

    original_filename = upload_file.filename or "upload"
    dest_path = subdir / original_filename

    with dest_path.open("wb") as dest:
        shutil.copyfileobj(upload_file.file, dest)

    file_size = dest_path.stat().st_size
    return dest_path, file_size


def delete_document_files(file_path: str | Path) -> None:
    """Delete the document file and its parent UUID subdirectory."""
    file_path = Path(file_path)
    parent = file_path.parent
    if parent.exists():
        shutil.rmtree(parent)


def get_document_path(file_path: str | Path) -> Path:
    """Return a verified Path for the given file, raising FileNotFoundError if absent."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    return path
