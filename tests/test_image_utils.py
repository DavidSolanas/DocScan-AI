"""Tests for image utility functions."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from backend.utils.image_utils import (
    cv2_to_pil,
    load_image,
    pdf_page_count,
    pdf_page_to_image,
    pil_to_cv2,
)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    import fitz

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello World test document")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    cv2.putText(img, "Test", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    img_path = tmp_path / "test.png"
    cv2.imwrite(str(img_path), img)
    return img_path


def test_pdf_page_to_image(sample_pdf: Path):
    img = pdf_page_to_image(sample_pdf, 0, dpi=150)
    assert isinstance(img, np.ndarray)
    assert len(img.shape) == 3
    assert img.shape[2] == 3  # BGR


def test_pdf_page_count(sample_pdf: Path):
    count = pdf_page_count(sample_pdf)
    assert count == 1


def test_pdf_page_count_multipage(tmp_path: Path):
    import fitz

    pdf_path = tmp_path / "multi.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    doc.save(str(pdf_path))
    doc.close()
    assert pdf_page_count(pdf_path) == 3


def test_load_image(sample_image: Path):
    img = load_image(sample_image)
    assert isinstance(img, np.ndarray)
    assert img.shape == (100, 200, 3)


def test_load_image_unsupported_format(tmp_path: Path):
    fake_path = tmp_path / "test.xyz"
    fake_path.write_text("not an image")
    with pytest.raises(ValueError, match="Unsupported image format"):
        load_image(fake_path)


def test_pil_to_cv2_rgb():
    pil_img = Image.new("RGB", (50, 30), color=(255, 0, 0))
    cv_img = pil_to_cv2(pil_img)
    assert cv_img.shape == (30, 50, 3)
    # Red in RGB -> Blue channel in BGR should be 255
    assert cv_img[0, 0, 0] == 0  # B
    assert cv_img[0, 0, 2] == 255  # R


def test_pil_to_cv2_grayscale():
    pil_img = Image.new("L", (50, 30), color=128)
    cv_img = pil_to_cv2(pil_img)
    assert cv_img.shape == (30, 50, 3)  # Converted to BGR


def test_cv2_to_pil_color():
    cv_img = np.zeros((30, 50, 3), dtype=np.uint8)
    cv_img[:, :, 2] = 255  # Red in BGR
    pil_img = cv2_to_pil(cv_img)
    assert pil_img.mode == "RGB"
    assert pil_img.size == (50, 30)
    r, g, b = pil_img.getpixel((0, 0))
    assert r == 255
    assert g == 0
    assert b == 0


def test_cv2_to_pil_grayscale():
    cv_img = np.full((30, 50), 128, dtype=np.uint8)
    pil_img = cv2_to_pil(cv_img)
    assert pil_img.mode == "L"
    assert pil_img.size == (50, 30)
