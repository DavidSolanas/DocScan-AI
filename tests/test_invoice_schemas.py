# tests/test_invoice_schemas.py
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.schemas.invoice import Invoice, InvoiceLine, InvoiceType, TaxBreakdown


def _make_line(**kwargs) -> InvoiceLine:
    defaults = {
        "line_number": 1,
        "description": "Test service",
        "base_amount": Decimal("100.00"),
        "iva_rate": Decimal("21"),
        "iva_amount": Decimal("21.00"),
        "total_line": Decimal("121.00"),
    }
    defaults.update(kwargs)
    return InvoiceLine(**defaults)


def _make_invoice(**kwargs) -> Invoice:
    line = _make_line()
    defaults = {
        "invoice_type": InvoiceType.STANDARD,
        "invoice_number": "F-001",
        "issue_date": date(2026, 3, 15),
        "issuer_name": "Acme SL",
        "issuer_cif": "B12345679",
        "recipient_name": "Client SA",
        "recipient_cif": "A87654321",
        "lines": [line],
        "tax_breakdown": [],
        "subtotal": Decimal("100.00"),
        "total_iva": Decimal("21.00"),
        "total_amount": Decimal("121.00"),
        "source_file": "test.pdf",
        "extraction_confidence": 0.95,
    }
    defaults.update(kwargs)
    return Invoice(**defaults)


def test_invoice_type_enum_values():
    assert InvoiceType.STANDARD == "STANDARD"
    assert InvoiceType.SIMPLIFIED == "SIMPLIFIED"
    assert InvoiceType("RECTIFICATIVE") == InvoiceType.RECTIFICATIVE


def test_invoice_line_decimal_fields():
    line = _make_line(quantity=Decimal("2"), unit_price=Decimal("50.00"))
    assert isinstance(line.base_amount, Decimal)
    assert line.quantity == Decimal("2")


def test_invoice_line_optional_defaults_none():
    line = _make_line()
    assert line.quantity is None
    assert line.unit is None
    assert line.recargo_equivalencia_rate is None


def test_invoice_decimal_serialization_as_string():
    """model_dump_json() must serialize Decimal as string, not float."""
    line = _make_line()
    data = json.loads(line.model_dump_json())
    assert isinstance(data["base_amount"], str), "Decimal must serialize as string"
    assert data["base_amount"] == "100.00"


def test_invoice_defaults():
    invoice = _make_invoice()
    assert invoice.currency == "EUR"
    assert invoice.language == "es"
    assert invoice.issuer_country == "ES"
    assert invoice.requires_manual_review is False
    assert invoice.review_reasons == []


def test_invoice_model_dump_json_decimal():
    invoice = _make_invoice()
    data = json.loads(invoice.model_dump_json())
    assert isinstance(data["subtotal"], str)
    assert isinstance(data["total_amount"], str)


def test_invoice_missing_required_raises():
    with pytest.raises(ValidationError):
        Invoice(invoice_type=InvoiceType.STANDARD)  # type: ignore[call-arg]
