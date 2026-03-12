"""Image conversion utilities for PDF pages, PIL, and OpenCV arrays."""

from __future__ import annotations

from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image

# Formats supported by load_image
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


def pdf_page_to_image(file_path: str | Path, page_number: int, dpi: int = 300) -> np.ndarray:
    """Rasterize a single PDF page to a BGR numpy array.

    Args:
        file_path: Path to the PDF file.
        page_number: Zero-based page index.
        dpi: Target resolution.

    Returns:
        BGR numpy array (OpenCV convention).
    """
    doc = fitz.open(str(file_path))
    try:
        page = doc[page_number]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        # Convert RGB(A) -> BGR
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        return img
    finally:
        doc.close()


def pdf_page_count(file_path: str | Path) -> int:
    """Return the number of pages in a PDF without loading all pages."""
    doc = fitz.open(str(file_path))
    try:
        return len(doc)
    finally:
        doc.close()


def load_image(file_path: str | Path) -> np.ndarray:
    """Load an image file (PNG/JPG/TIFF/BMP/WEBP) as a BGR numpy array."""
    path = Path(file_path)
    if path.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image format: {path.suffix}")
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Failed to load image: {path}")
    return img


def pil_to_cv2(pil_image: Image.Image) -> np.ndarray:
    """Convert a PIL Image to a BGR numpy array."""
    arr = np.array(pil_image)
    if pil_image.mode == "RGB":
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    if pil_image.mode == "RGBA":
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    if pil_image.mode == "L":
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    # Fallback: convert to RGB first
    return cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)


def cv2_to_pil(cv_image: np.ndarray) -> Image.Image:
    """Convert a BGR numpy array to a PIL RGB Image."""
    if len(cv_image.shape) == 2:
        return Image.fromarray(cv_image, mode="L")
    return Image.fromarray(cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB))
