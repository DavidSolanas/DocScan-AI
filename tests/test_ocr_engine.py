"""Tests for OCR engine — pytesseract is mocked (no system Tesseract needed)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from backend.services.ocr_engine import (
    OCRResult,
    _parse_hocr,
    build_ocr_result,
)

SAMPLE_HOCR = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<body>
<div class="ocr_page" title="bbox 0 0 2550 3300">
  <span class="ocr_line" title="bbox 100 100 500 140">
    <span class="ocrx_word" title="bbox 100 100 200 140; x_wconf 95">Hello</span>
    <span class="ocrx_word" title="bbox 210 100 320 140; x_wconf 82">World</span>
  </span>
  <span class="ocr_line" title="bbox 100 160 500 200">
    <span class="ocrx_word" title="bbox 100 160 250 200; x_wconf 45">blurry</span>
  </span>
</div>
</body>
</html>"""


def test_parse_hocr_extracts_words():
    words = _parse_hocr(SAMPLE_HOCR, 1)
    assert len(words) == 3
    assert words[0].text == "Hello"
    assert words[0].confidence == 95.0
    assert words[0].bbox == (100, 100, 200, 140)
    assert words[1].text == "World"
    assert words[1].confidence == 82.0
    assert words[2].text == "blurry"
    assert words[2].confidence == 45.0


def test_parse_hocr_empty():
    words = _parse_hocr("<html><body></body></html>", 1)
    assert words == []


def test_parse_hocr_malformed():
    words = _parse_hocr("not valid xml at all <<<>>>", 1)
    assert words == []


def test_build_ocr_result_empty():
    result = build_ocr_result([])
    assert isinstance(result, OCRResult)
    assert result.full_text == ""
    assert result.average_confidence == 0.0
    assert result.low_confidence_pages == []


def test_build_ocr_result_combines_pages():
    from backend.services.ocr_engine import OCRPageResult, OCRWord

    page1 = OCRPageResult(
        page_number=1,
        text="Page one text",
        words=[OCRWord(text="Page", confidence=90.0, bbox=(0, 0, 0, 0))],
        average_confidence=90.0,
        low_confidence=False,
    )
    page2 = OCRPageResult(
        page_number=2,
        text="Page two text",
        words=[OCRWord(text="Page", confidence=50.0, bbox=(0, 0, 0, 0))],
        average_confidence=50.0,
        low_confidence=True,
    )
    result = build_ocr_result([page1, page2])
    assert "Page one text" in result.full_text
    assert "Page two text" in result.full_text
    assert result.average_confidence == 70.0
    assert result.low_confidence_pages == [2]
    assert len(result.pages) == 2


@pytest.mark.asyncio
async def test_ocr_page_mocked():
    from backend.services.ocr_engine import ocr_page

    test_image = np.zeros((100, 200), dtype=np.uint8)

    with (
        patch("backend.services.ocr_engine.pytesseract.image_to_string", return_value="Test text"),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=SAMPLE_HOCR.encode("utf-8"),
        ),
    ):
        result = await ocr_page(test_image, 1, "eng", 3, 70.0)

    assert result.page_number == 1
    assert result.text == "Test text"
    assert len(result.words) == 3
    assert result.average_confidence > 0
