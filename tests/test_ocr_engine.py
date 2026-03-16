"""Tests for OCR engine — pytesseract is mocked (no system Tesseract needed)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.services.ocr_engine import (
    OCREngine,
    OCRResult,
    _parse_hocr,
    _garbage_ratio,
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


# ──────────────────────────────────────────────────────────────────────────────
# OCREngine enum
# ──────────────────────────────────────────────────────────────────────────────

def test_ocr_engine_enum_values():
    assert OCREngine.TESSERACT == "tesseract"
    assert OCREngine.GLM_OCR == "glm_ocr"
    assert not hasattr(OCREngine, "PADDLEOCR")


# ──────────────────────────────────────────────────────────────────────────────
# _garbage_ratio
# ──────────────────────────────────────────────────────────────────────────────

def test_garbage_ratio_clean_text():
    assert _garbage_ratio("Factura 123 Total 100€") == 0.0


def test_garbage_ratio_garbage_text():
    assert _garbage_ratio("###^^^&&&***~~~" * 5) == 1.0


def test_garbage_ratio_empty_string():
    assert _garbage_ratio("") == 1.0


def test_garbage_ratio_all_valid():
    assert _garbage_ratio("Hello World!") == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# ocr_page_glm
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ocr_page_glm_success():
    """GLM-OCR clean output → confidence 85.0, low_confidence=False, empty words."""
    from backend.services.ocr_engine import ocr_page_glm
    from unittest.mock import AsyncMock

    image = np.zeros((100, 200), dtype=np.uint8)
    mock_provider = MagicMock()
    mock_provider.complete_vision = AsyncMock(return_value="Factura nº 123\nTotal: 121,00 €")

    with patch("backend.services.ocr_engine._make_glm_provider", return_value=mock_provider):
        result = await ocr_page_glm(image, 1)

    assert result.page_number == 1
    assert result.text == "Factura nº 123\nTotal: 121,00 €"
    assert result.average_confidence == 85.0
    assert result.low_confidence is False
    assert result.words == []


@pytest.mark.asyncio
async def test_ocr_page_glm_empty_output_low_confidence():
    """GLM-OCR empty output → confidence 0.0, low_confidence=True."""
    from backend.services.ocr_engine import ocr_page_glm
    from unittest.mock import AsyncMock

    image = np.zeros((100, 200), dtype=np.uint8)
    mock_provider = MagicMock()
    mock_provider.complete_vision = AsyncMock(return_value="   ")  # whitespace only

    with patch("backend.services.ocr_engine._make_glm_provider", return_value=mock_provider):
        result = await ocr_page_glm(image, 1)

    assert result.average_confidence == 0.0
    assert result.low_confidence is True


@pytest.mark.asyncio
async def test_ocr_page_glm_garbage_output_low_confidence():
    """GLM-OCR high garbage ratio → confidence 30.0, low_confidence=True."""
    from backend.services.ocr_engine import ocr_page_glm
    from unittest.mock import AsyncMock

    image = np.zeros((100, 200), dtype=np.uint8)
    garbage = "###^^^&&&***~~~" * 5
    mock_provider = MagicMock()
    mock_provider.complete_vision = AsyncMock(return_value=garbage)

    with patch("backend.services.ocr_engine._make_glm_provider", return_value=mock_provider):
        result = await ocr_page_glm(image, 1)

    assert result.average_confidence == 30.0
    assert result.low_confidence is True


# ──────────────────────────────────────────────────────────────────────────────
# ocr_page_routed
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_glm_ocr_success_returns_glm_engine():
    """Clean GLM-OCR output → engine_used = GLM_OCR."""
    from backend.services.ocr_engine import ocr_page_routed
    from unittest.mock import AsyncMock

    image = np.zeros((100, 200), dtype=np.uint8)
    mock_provider = MagicMock()
    mock_provider.complete_vision = AsyncMock(return_value="Factura 123 Total 100€")

    with patch("backend.services.ocr_engine._make_glm_provider", return_value=mock_provider):
        result, engine = await ocr_page_routed(image, 1, glm_ocr_enabled=True)

    assert engine == OCREngine.GLM_OCR
    assert result.text == "Factura 123 Total 100€"


@pytest.mark.asyncio
async def test_glm_ocr_empty_output_falls_back_to_tesseract():
    """Empty GLM-OCR output → Tesseract fallback."""
    from backend.services.ocr_engine import ocr_page_routed
    from unittest.mock import AsyncMock

    image = np.zeros((100, 200), dtype=np.uint8)
    mock_provider = MagicMock()
    mock_provider.complete_vision = AsyncMock(return_value="")

    with (
        patch("backend.services.ocr_engine._make_glm_provider", return_value=mock_provider),
        patch("backend.services.ocr_engine.pytesseract.image_to_string", return_value="Fallback text"),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=SAMPLE_HOCR.encode("utf-8"),
        ),
    ):
        result, engine = await ocr_page_routed(image, 1, glm_ocr_enabled=True)

    assert engine == OCREngine.TESSERACT
    assert result.text == "Fallback text"


@pytest.mark.asyncio
async def test_glm_ocr_garbage_output_falls_back_to_tesseract():
    """High garbage ratio → low_confidence → Tesseract fallback."""
    from backend.services.ocr_engine import ocr_page_routed
    from unittest.mock import AsyncMock

    image = np.zeros((100, 200), dtype=np.uint8)
    mock_provider = MagicMock()
    mock_provider.complete_vision = AsyncMock(return_value="###^^^&&&***~~~" * 5)

    with (
        patch("backend.services.ocr_engine._make_glm_provider", return_value=mock_provider),
        patch("backend.services.ocr_engine.pytesseract.image_to_string", return_value="Clean text"),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=SAMPLE_HOCR.encode("utf-8"),
        ),
    ):
        result, engine = await ocr_page_routed(image, 1, glm_ocr_enabled=True)

    assert engine == OCREngine.TESSERACT


@pytest.mark.asyncio
async def test_glm_ocr_ollama_error_falls_back_to_tesseract():
    """Ollama connection error → Tesseract fallback, error never surfaces."""
    from backend.services.ocr_engine import ocr_page_routed
    from backend.services.llm_service import LLMConnectionError
    from unittest.mock import AsyncMock

    image = np.zeros((100, 200), dtype=np.uint8)
    mock_provider = MagicMock()
    mock_provider.complete_vision = AsyncMock(side_effect=LLMConnectionError("offline"))

    with (
        patch("backend.services.ocr_engine._make_glm_provider", return_value=mock_provider),
        patch("backend.services.ocr_engine.pytesseract.image_to_string", return_value="Tesseract text"),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=SAMPLE_HOCR.encode("utf-8"),
        ),
    ):
        result, engine = await ocr_page_routed(image, 1, glm_ocr_enabled=True)

    assert engine == OCREngine.TESSERACT
    assert result.text == "Tesseract text"


@pytest.mark.asyncio
async def test_glm_ocr_disabled_uses_tesseract_directly():
    """glm_ocr_enabled=False → Tesseract runs directly, GLM-OCR never called."""
    from backend.services.ocr_engine import ocr_page_routed
    from unittest.mock import AsyncMock

    image = np.zeros((100, 200), dtype=np.uint8)
    mock_provider = MagicMock()
    mock_provider.complete_vision = AsyncMock(return_value="should not be called")

    with (
        patch("backend.services.ocr_engine._make_glm_provider", return_value=mock_provider),
        patch("backend.services.ocr_engine.pytesseract.image_to_string", return_value="Direct tesseract"),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=SAMPLE_HOCR.encode("utf-8"),
        ),
    ):
        result, engine = await ocr_page_routed(image, 1, glm_ocr_enabled=False)

    assert engine == OCREngine.TESSERACT
    mock_provider.complete_vision.assert_not_called()
