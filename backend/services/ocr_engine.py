"""Tesseract OCR engine with HOCR parsing for word-level confidence."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

import numpy as np
import pytesseract
from PIL import Image


@dataclass
class OCRWord:
    text: str
    confidence: float  # 0-100
    bbox: tuple[int, int, int, int]


@dataclass
class OCRPageResult:
    page_number: int
    text: str
    words: list[OCRWord] = field(default_factory=list)
    average_confidence: float = 0.0
    low_confidence: bool = False


@dataclass
class OCRResult:
    pages: list[OCRPageResult] = field(default_factory=list)
    full_text: str = ""
    average_confidence: float = 0.0
    low_confidence_pages: list[int] = field(default_factory=list)


def _parse_hocr(hocr_html: str, page_number: int) -> list[OCRWord]:
    """Parse HOCR HTML to extract words with confidence and bounding boxes."""
    words: list[OCRWord] = []

    # HOCR may not be strict XHTML; fix common issues
    # Wrap in root if needed and parse
    try:
        root = ElementTree.fromstring(hocr_html)
    except ElementTree.ParseError:
        # Try wrapping in a root element
        try:
            root = ElementTree.fromstring(f"<root>{hocr_html}</root>")
        except ElementTree.ParseError:
            return words

    # Find all ocrx_word spans
    ns = {"html": "http://www.w3.org/1999/xhtml"}

    # Search both with and without namespace
    for span in _find_all_ocr_words(root, ns):
        title = span.get("title", "")
        text = (span.text or "").strip()
        if not text:
            continue

        # Parse bbox: "bbox x1 y1 x2 y2"
        bbox_match = re.search(r"bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", title)
        # Parse confidence: "x_wconf NN"
        conf_match = re.search(r"x_wconf\s+(\d+)", title)

        bbox = (0, 0, 0, 0)
        if bbox_match:
            bbox = (
                int(bbox_match.group(1)),
                int(bbox_match.group(2)),
                int(bbox_match.group(3)),
                int(bbox_match.group(4)),
            )

        confidence = float(conf_match.group(1)) if conf_match else 0.0

        words.append(OCRWord(text=text, confidence=confidence, bbox=bbox))

    return words


def _find_all_ocr_words(root: ElementTree.Element, ns: dict) -> list[ElementTree.Element]:
    """Find all ocrx_word spans, with or without XHTML namespace."""
    results = []
    # Without namespace
    for span in root.iter("span"):
        cls = span.get("class", "")
        if "ocrx_word" in cls:
            results.append(span)
    # With namespace
    for span in root.iter("{http://www.w3.org/1999/xhtml}span"):
        cls = span.get("class", "")
        if "ocrx_word" in cls:
            results.append(span)
    return results


def _ocr_page_sync(
    image: np.ndarray,
    page_number: int,
    lang: str = "spa+eng",
    psm: int = 3,
    confidence_threshold: float = 70.0,
) -> OCRPageResult:
    """Run Tesseract on a single page image, returning structured results."""
    pil_image = Image.fromarray(image)

    custom_config = f"--psm {psm}"

    # Get plain text
    text = pytesseract.image_to_string(pil_image, lang=lang, config=custom_config)

    # Get HOCR for word-level confidence
    hocr = pytesseract.image_to_pdf_or_hocr(
        pil_image, lang=lang, config=custom_config, extension="hocr"
    )
    hocr_str = hocr.decode("utf-8") if isinstance(hocr, bytes) else hocr

    words = _parse_hocr(hocr_str, page_number)

    avg_confidence = 0.0
    if words:
        avg_confidence = sum(w.confidence for w in words) / len(words)

    return OCRPageResult(
        page_number=page_number,
        text=text.strip(),
        words=words,
        average_confidence=round(avg_confidence, 1),
        low_confidence=avg_confidence < confidence_threshold,
    )


async def ocr_page(
    image: np.ndarray,
    page_number: int,
    lang: str = "spa+eng",
    psm: int = 3,
    confidence_threshold: float = 70.0,
) -> OCRPageResult:
    """Async wrapper for OCR on a single page."""
    return await asyncio.to_thread(
        _ocr_page_sync, image, page_number, lang, psm, confidence_threshold
    )


def build_ocr_result(page_results: list[OCRPageResult]) -> OCRResult:
    """Assemble an OCRResult from a list of per-page results."""
    if not page_results:
        return OCRResult()

    full_text = "\n\n".join(p.text for p in page_results if p.text)
    all_confidences = [p.average_confidence for p in page_results if p.words]
    avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
    low_pages = [p.page_number for p in page_results if p.low_confidence]

    return OCRResult(
        pages=page_results,
        full_text=full_text,
        average_confidence=round(avg_confidence, 1),
        low_confidence_pages=low_pages,
    )
