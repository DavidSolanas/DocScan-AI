# tests/test_invoice_extractor_table_aware.py
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.schemas.invoice import Invoice, InvoiceType
from backend.services.invoice_extractor import (
    extract_invoice,
    extract_line_items,
    table_to_line_items_context,
)
from backend.services.llm_service import LLMService
from backend.services.table_extractor import ExtractedTable, TableCell


# ---- Helpers ----

def _make_table(nrows: int, ncols: int, page: int = 1, method: str = "pdfplumber") -> ExtractedTable:
    cells = [
        TableCell(row=r, col=c, text=f"cell{r}{c}")
        for r in range(nrows)
        for c in range(ncols)
    ]
    return ExtractedTable(cells=cells, num_rows=nrows, num_cols=ncols, extraction_method=method, page_number=page)


def _make_llm(responses: list[str]) -> LLMService:
    call_count = 0

    async def fake_complete(prompt, system=None, json_mode=False):
        nonlocal call_count
        r = responses[call_count % len(responses)]
        call_count += 1
        return r

    svc = LLMService.__new__(LLMService)
    svc._provider = MagicMock()
    svc._provider.complete = AsyncMock(side_effect=fake_complete)
    svc._max_retries = 2
    return svc


def _capture_llm(captured: list) -> LLMService:
    """LLM that records prompts and returns minimal valid JSON."""
    async def fake_complete(prompt, system=None, json_mode=False):
        captured.append(prompt)
        return "[]"

    svc = LLMService.__new__(LLMService)
    svc._provider = MagicMock()
    svc._provider.complete = AsyncMock(side_effect=fake_complete)
    svc._max_retries = 2
    return svc


# ---- table_to_line_items_context ----

def test_table_to_line_items_context_formats_correctly():
    table = _make_table(2, 3, page=1, method="camelot")
    ctx = table_to_line_items_context([table])
    assert "Table (page 1, method camelot, 2×3):" in ctx
    # Pipe-delimited rows
    assert "| cell00 | cell01 | cell02 |" in ctx
    assert "| cell10 | cell11 | cell12 |" in ctx


def test_table_to_line_items_context_empty_table_skipped():
    empty = ExtractedTable(cells=[], num_rows=0, num_cols=0)
    ctx = table_to_line_items_context([empty])
    assert ctx == ""


def test_table_to_line_items_context_truncates_at_50_rows():
    table = _make_table(60, 2, page=1)
    ctx = table_to_line_items_context([table])
    # Only 50 rows should appear; count pipe-delimited lines
    row_lines = [line for line in ctx.split("\n") if line.strip().startswith("|")]
    assert len(row_lines) == 50


# ---- extract_line_items ----

async def test_extract_line_items_no_tables_uses_text_only_prompt():
    captured: list[str] = []
    svc = _capture_llm(captured)
    await extract_line_items("invoice text", InvoiceType.STANDARD, svc, tables=None)
    assert len(captured) == 1
    assert "STRUCTURED TABLE DATA" not in captured[0]


async def test_extract_line_items_with_tables_includes_structured_hint():
    captured: list[str] = []
    svc = _capture_llm(captured)
    table = _make_table(3, 3, page=1, method="pdfplumber")
    await extract_line_items("invoice text", InvoiceType.STANDARD, svc, tables=[table])
    assert len(captured) == 1
    prompt = captured[0]
    assert "STRUCTURED TABLE DATA" in prompt
    # Cell text from to_matrix() should appear
    assert "cell00" in prompt


# ---- extract_invoice ----

async def test_extract_invoice_passes_tables_to_line_items():
    """Verify the line-items pass (pass 3) receives structured hint when tables provided."""
    captured: list[str] = []

    call_idx = 0
    responses = [
        "STANDARD",                                    # pass 1: classify
        json.dumps({"invoice_number": "F-001", "issue_date": "2026-03-15",
                    "issuer_name": "Acme", "issuer_cif": "A12345679",
                    "issuer_address": "C/Mayor 1", "recipient_name": "Client",
                    "recipient_cif": "12345678Z"}),    # pass 2: headers
        "[]",                                          # pass 3: line items
        json.dumps({"subtotal": "100.00", "total_iva": "21.00",
                    "total_amount": "121.00"}),         # pass 4: totals
    ]

    async def fake_complete(prompt, system=None, json_mode=False):
        nonlocal call_idx
        captured.append(prompt)
        r = responses[call_idx % len(responses)]
        call_idx += 1
        return r

    svc = LLMService.__new__(LLMService)
    svc._provider = MagicMock()
    svc._provider.complete = AsyncMock(side_effect=fake_complete)
    svc._max_retries = 2

    table = _make_table(3, 3, page=1, method="pdfplumber")
    await extract_invoice("invoice text with factura nif iva base imponible total", "test.pdf", svc, tables=[table])

    # The third call (index 2) is the line-items pass
    assert len(captured) >= 3
    line_items_prompt = captured[2]
    assert "STRUCTURED TABLE DATA" in line_items_prompt
    assert "cell00" in line_items_prompt


async def test_extract_invoice_no_tables_backward_compat():
    """Calling extract_invoice without tables must still return a valid Invoice."""
    responses = [
        "STANDARD",
        json.dumps({"invoice_number": "F-001", "issue_date": "2026-03-15",
                    "issuer_name": "Acme", "issuer_cif": "A12345679",
                    "issuer_address": "C/Mayor 1", "recipient_name": "Client",
                    "recipient_cif": "12345678Z"}),
        "[]",
        json.dumps({"subtotal": "100.00", "total_iva": "21.00",
                    "total_amount": "121.00"}),
    ]
    svc = _make_llm(responses)
    invoice, result = await extract_invoice(
        "invoice text with factura nif iva base imponible total", "test.pdf", svc
    )
    assert isinstance(invoice, Invoice)
