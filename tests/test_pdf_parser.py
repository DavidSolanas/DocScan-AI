from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.services.pdf_parser import parse_pdf


@pytest.mark.asyncio
async def test_parse_digital_pdf(sample_pdf: Path) -> None:
    result = await parse_pdf(sample_pdf)
    assert "Hello World" in result.text
    assert result.page_count == 1
    assert result.is_scanned is False


@pytest.mark.asyncio
async def test_parse_empty_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    result = await parse_pdf(pdf_path)
    assert result.text.strip() == ""
    assert result.is_scanned is False


@pytest.mark.asyncio
async def test_parse_multipage_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "multipage.pdf"
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} content")
    doc.save(str(pdf_path))
    doc.close()

    result = await parse_pdf(pdf_path)
    assert result.page_count == 3
    assert "Page 1 content" in result.text
    assert "Page 2 content" in result.text
    assert "Page 3 content" in result.text
