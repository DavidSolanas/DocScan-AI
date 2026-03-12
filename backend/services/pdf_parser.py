from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PDFParseResult:
    text: str
    page_texts: list[str]
    page_count: int
    is_scanned: bool


def _parse_pdf_sync(file_path: str | Path) -> PDFParseResult:
    import fitz  # PyMuPDF — imported here to keep it isolated per thread call

    file_path = Path(file_path)
    doc = fitz.open(str(file_path))
    try:
        page_texts: list[str] = []
        is_scanned = False

        for page in doc:
            page_text = page.get_text()
            page_texts.append(page_text)

            # A page is considered scanned when it has very little extractable text
            # but contains at least one embedded image.
            if len(page_text.strip()) < 10 and len(page.get_images()) > 0:
                is_scanned = True

        full_text = "\n".join(page_texts)
        return PDFParseResult(
            text=full_text,
            page_texts=page_texts,
            page_count=len(page_texts),
            is_scanned=is_scanned,
        )
    finally:
        doc.close()


async def parse_pdf(file_path: str | Path) -> PDFParseResult:
    """Parse a PDF file asynchronously, wrapping sync fitz calls in a thread."""
    return await asyncio.to_thread(_parse_pdf_sync, file_path)
