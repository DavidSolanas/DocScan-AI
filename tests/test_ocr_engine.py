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
    assert _garbage_ratio("Factura 123 Total 100€") < 0.15


def test_garbage_ratio_garbage_text():
    assert _garbage_ratio("###^^^&&&***~~~" * 5) > 0.15


def test_garbage_ratio_empty_string():
    assert _garbage_ratio("") == 1.0


def test_garbage_ratio_all_valid():
    assert _garbage_ratio("Hello World!") == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# _paddleocr_page_sync
# ──────────────────────────────────────────────────────────────────────────────

def test_paddleocr_page_sync_raises_when_not_installed():
    from backend.services.ocr_engine import _paddleocr_page_sync

    image = np.zeros((100, 200), dtype=np.uint8)
    with patch.dict("sys.modules", {"paddleocr": None}):
        with pytest.raises(RuntimeError, match="PaddleOCR not installed"):
            _paddleocr_page_sync(image, page_number=1)


def test_paddleocr_page_sync_mocked():
    from backend.services.ocr_engine import _paddleocr_page_sync

    image = np.zeros((100, 200), dtype=np.uint8)

    # Simulate PaddleOCR result: list of list of [bbox_points, (text, score)]
    fake_result = [
        [
            [[10, 10], [100, 10], [100, 30], [10, 30]],
            ("Factura", 0.92),
        ],
        [
            [[10, 40], [200, 40], [200, 60], [10, 60]],
            ("NIF: B12345678", 0.85),
        ],
    ]

    mock_paddle_instance = MagicMock()
    mock_paddle_instance.ocr.return_value = [fake_result]

    mock_paddleocr_module = MagicMock()
    mock_paddleocr_module.PaddleOCR.return_value = mock_paddle_instance

    with patch.dict("sys.modules", {"paddleocr": mock_paddleocr_module}):
        result = _paddleocr_page_sync(image, page_number=1, lang="spa+eng")

    assert result.page_number == 1
    assert "Factura" in result.text
    assert len(result.words) == 2
    assert result.words[0].confidence == pytest.approx(92.0)
    assert result.words[1].text == "NIF: B12345678"


# ──────────────────────────────────────────────────────────────────────────────
# Dual-engine routing
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_engine_uses_tesseract_on_high_confidence():
    """When Tesseract confidence is >= threshold, PaddleOCR should not be called."""
    from backend.services.ocr_engine import ocr_page_dual_engine

    image = np.zeros((100, 200), dtype=np.uint8)

    high_conf_hocr = SAMPLE_HOCR  # avg confidence ~74%, above 70 threshold

    with (
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_string",
            return_value="High confidence text",
        ),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=high_conf_hocr.encode("utf-8"),
        ),
    ):
        result, engine = await ocr_page_dual_engine(
            image, 1, "spa+eng", 3, 70.0, paddleocr_enabled=True
        )

    assert engine == OCREngine.TESSERACT
    assert result.page_number == 1


@pytest.mark.asyncio
async def test_dual_engine_falls_back_to_paddle_on_low_confidence():
    """When Tesseract gives low confidence, PaddleOCR should be tried."""
    from backend.services.ocr_engine import ocr_page_dual_engine

    image = np.zeros((100, 200), dtype=np.uint8)

    # HOCR with only a 45-confidence word → low_confidence=True
    low_conf_hocr = """<html><body>
    <span class="ocrx_word" title="bbox 0 0 50 20; x_wconf 45">blurry</span>
    </body></html>"""

    fake_paddle_result = [
        [
            [[10, 10], [100, 10], [100, 30], [10, 30]],
            ("ClearText", 0.95),
        ]
    ]
    mock_paddle_instance = MagicMock()
    mock_paddle_instance.ocr.return_value = [fake_paddle_result]
    mock_paddleocr_module = MagicMock()
    mock_paddleocr_module.PaddleOCR.return_value = mock_paddle_instance

    with (
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_string",
            return_value="blurry",
        ),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=low_conf_hocr.encode("utf-8"),
        ),
        patch.dict("sys.modules", {"paddleocr": mock_paddleocr_module}),
    ):
        result, engine = await ocr_page_dual_engine(
            image, 1, "spa+eng", 3, 70.0, paddleocr_enabled=True
        )

    assert engine == OCREngine.PADDLEOCR
    assert "ClearText" in result.text
    assert result.average_confidence == pytest.approx(95.0)


@pytest.mark.asyncio
async def test_dual_engine_skips_paddle_when_disabled():
    """When paddleocr_enabled=False, should always use Tesseract."""
    from backend.services.ocr_engine import ocr_page_dual_engine

    image = np.zeros((100, 200), dtype=np.uint8)
    low_conf_hocr = """<html><body>
    <span class="ocrx_word" title="bbox 0 0 50 20; x_wconf 30">bad</span>
    </body></html>"""

    with (
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_string",
            return_value="bad",
        ),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=low_conf_hocr.encode("utf-8"),
        ),
    ):
        result, engine = await ocr_page_dual_engine(
            image, 1, "spa+eng", 3, 70.0, paddleocr_enabled=False
        )

    assert engine == OCREngine.TESSERACT


@pytest.mark.asyncio
async def test_dual_engine_keeps_tesseract_when_paddle_not_installed():
    """When PaddleOCR is not installed, fall back to Tesseract result."""
    from backend.services.ocr_engine import ocr_page_dual_engine

    image = np.zeros((100, 200), dtype=np.uint8)
    low_conf_hocr = """<html><body>
    <span class="ocrx_word" title="bbox 0 0 50 20; x_wconf 30">bad</span>
    </body></html>"""

    with (
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_string",
            return_value="bad",
        ),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=low_conf_hocr.encode("utf-8"),
        ),
        patch.dict("sys.modules", {"paddleocr": None}),
    ):
        result, engine = await ocr_page_dual_engine(
            image, 1, "spa+eng", 3, 70.0, paddleocr_enabled=True
        )

    # PaddleOCR not installed → RuntimeError caught → keep Tesseract
    assert engine == OCREngine.TESSERACT


@pytest.mark.asyncio
async def test_dual_engine_keeps_tesseract_when_paddle_has_lower_confidence():
    """If PaddleOCR confidence is lower than Tesseract, keep Tesseract result."""
    from backend.services.ocr_engine import ocr_page_dual_engine

    image = np.zeros((100, 200), dtype=np.uint8)
    low_conf_hocr = """<html><body>
    <span class="ocrx_word" title="bbox 0 0 50 20; x_wconf 60">text</span>
    </body></html>"""

    # PaddleOCR returns even lower confidence
    fake_paddle_result = [
        [
            [[0, 0], [50, 0], [50, 20], [0, 20]],
            ("worse", 0.40),
        ]
    ]
    mock_paddle_instance = MagicMock()
    mock_paddle_instance.ocr.return_value = [fake_paddle_result]
    mock_paddleocr_module = MagicMock()
    mock_paddleocr_module.PaddleOCR.return_value = mock_paddle_instance

    with (
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_string",
            return_value="text",
        ),
        patch(
            "backend.services.ocr_engine.pytesseract.image_to_pdf_or_hocr",
            return_value=low_conf_hocr.encode("utf-8"),
        ),
        patch.dict("sys.modules", {"paddleocr": mock_paddleocr_module}),
    ):
        result, engine = await ocr_page_dual_engine(
            image, 1, "spa+eng", 3, 70.0, paddleocr_enabled=True
        )

    # Tesseract (60%) > PaddleOCR (40%) → keep Tesseract
    assert engine == OCREngine.TESSERACT
