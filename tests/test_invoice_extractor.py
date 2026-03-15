# tests/test_invoice_extractor.py
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.schemas.invoice import Invoice, InvoiceType
from backend.services.invoice_extractor import (
    classify_document,
    extract_headers,
    extract_invoice,
    extract_line_items,
    extract_totals,
    is_likely_invoice,
)
from backend.services.llm_service import LLMConnectionError, LLMService, OllamaProvider


def _make_llm_with_response(response_text: str) -> tuple[LLMService, MagicMock]:
    """Return (LLMService, mock_client) where mock responds with response_text."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": response_text}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
    svc = LLMService(provider=provider, max_retries=2)
    return svc, mock_client


# ---- is_likely_invoice ----

def test_is_likely_invoice_true_with_three_keywords():
    text = "Factura número 001\nNIF del emisor: 12345678Z\nBase imponible: 100 EUR"
    assert is_likely_invoice(text) is True


def test_is_likely_invoice_false_with_two_keywords():
    text = "Factura número 001\nNIF del emisor"
    assert is_likely_invoice(text) is False


def test_is_likely_invoice_case_insensitive():
    text = "FACTURA 001 IVA TOTAL"
    assert is_likely_invoice(text) is True


def test_is_likely_invoice_false_for_plain_text():
    assert is_likely_invoice("Hello world this is a resume") is False


# ---- classify_document ----

async def test_classify_document_standard():
    svc, mock_client = _make_llm_with_response("STANDARD")
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        result = await classify_document("Factura de venta", svc)
    assert result == InvoiceType.STANDARD


async def test_classify_document_with_extra_text():
    # Model adds explanation text — regex extracts the type
    svc, mock_client = _make_llm_with_response("This looks like a SIMPLIFIED invoice.")
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        result = await classify_document("Ticket de venta", svc)
    assert result == InvoiceType.SIMPLIFIED


async def test_classify_document_defaults_to_standard_on_no_match():
    svc, mock_client = _make_llm_with_response("I cannot classify this.")
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        result = await classify_document("Random text", svc)
    assert result == InvoiceType.STANDARD


# ---- extract_headers ----

async def test_extract_headers_returns_dict():
    payload = {"invoice_number": "F-001", "issuer_name": "Acme SL", "issuer_cif": "A12345679"}
    svc, mock_client = _make_llm_with_response(json.dumps(payload))
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        result = await extract_headers("invoice text", InvoiceType.STANDARD, svc)
    assert result["invoice_number"] == "F-001"
    assert result["issuer_cif"] == "A12345679"


# ---- extract_line_items ----

async def test_extract_line_items_bare_list():
    lines = [{"line_number": 1, "description": "Srv", "base_amount": "100.00", "iva_rate": "21", "iva_amount": "21.00", "total_line": "121.00"}]
    svc, mock_client = _make_llm_with_response(json.dumps(lines))
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        result = await extract_line_items("invoice text", InvoiceType.STANDARD, svc)
    assert len(result) == 1


async def test_extract_line_items_wrapped_object():
    lines = [{"line_number": 1, "description": "Srv", "base_amount": "100.00", "iva_rate": "21", "iva_amount": "21.00", "total_line": "121.00"}]
    svc, mock_client = _make_llm_with_response(json.dumps({"lines": lines}))
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        result = await extract_line_items("invoice text", InvoiceType.STANDARD, svc)
    assert len(result) == 1


# ---- extract_totals ----

async def test_extract_totals_returns_dict():
    payload = {"subtotal": "100.00", "total_iva": "21.00", "total_amount": "121.00"}
    svc, mock_client = _make_llm_with_response(json.dumps(payload))
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        result = await extract_totals("invoice text", InvoiceType.STANDARD, svc)
    assert result["total_amount"] == "121.00"


# ---- extract_invoice orchestration ----

async def test_extract_invoice_full_pipeline():
    classify_resp = "STANDARD"
    headers_resp = json.dumps({
        "invoice_number": "F-001",
        "invoice_series": None,
        "issue_date": "2026-03-15",
        "service_date": None,
        "due_date": None,
        "issuer_name": "Acme SL",
        "issuer_cif": "A12345679",
        "issuer_address": "Calle Mayor 1",
        "issuer_postal_code": None,
        "issuer_city": "Madrid",
        "issuer_country": "ES",
        "recipient_name": "Client SA",
        "recipient_cif": "12345678Z",
        "recipient_address": None,
        "recipient_city": None,
        "language": "es",
    })
    lines_resp = json.dumps([{
        "line_number": 1,
        "description": "Service",
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "discount_pct": None,
        "base_amount": "100.00",
        "iva_rate": "21",
        "iva_amount": "21.00",
        "total_line": "121.00",
    }])
    totals_resp = json.dumps({
        "subtotal": "100.00",
        "total_iva": "21.00",
        "total_recargo": None,
        "irpf_rate": None,
        "irpf_amount": None,
        "total_amount": "121.00",
        "currency": "EUR",
        "payment_method": None,
        "payment_reference": None,
        "iban": None,
        "po_number": None,
        "original_invoice_ref": None,
        "rectification_reason": None,
        "notes": None,
    })

    responses = [classify_resp, headers_resp, lines_resp, totals_resp]
    call_count = 0

    async def fake_complete(prompt, system=None, json_mode=False):
        nonlocal call_count
        r = responses[call_count]
        call_count += 1
        return r

    svc = LLMService.__new__(LLMService)
    svc._provider = MagicMock()
    svc._provider.complete = AsyncMock(side_effect=fake_complete)
    svc._max_retries = 2

    invoice, result = await extract_invoice("Full invoice text", "test.pdf", svc)
    assert isinstance(invoice, Invoice)
    assert invoice.invoice_number == "F-001"
    assert invoice.invoice_type == InvoiceType.STANDARD


async def test_extract_invoice_llm_error_returns_partial():
    """LLMConnectionError on a pass → partial Invoice with review reasons, no raise."""
    svc = LLMService.__new__(LLMService)
    svc._provider = MagicMock()
    svc._provider.complete = AsyncMock(side_effect=LLMConnectionError("Ollama unreachable"))
    svc._max_retries = 2

    invoice, result = await extract_invoice("Some invoice text", "test.pdf", svc)
    assert isinstance(invoice, Invoice)
    assert invoice.requires_manual_review is True
    assert len(invoice.review_reasons) > 0
