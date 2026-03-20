# tests/test_invoice_validator_irpf_recargo.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.schemas.invoice import Invoice, InvoiceLine, InvoiceType
from backend.services.invoice_validator import (
    validate_invoice,
    validate_irpf_amount,
    validate_irpf_recargo_exclusivity,
    validate_recargo_iva_pairs,
    validate_total_recargo,
)


# ---- Helpers ----

def _make_line(**kwargs) -> InvoiceLine:
    defaults = {
        "line_number": 1,
        "description": "Service",
        "base_amount": Decimal("100.00"),
        "iva_rate": Decimal("21"),
        "iva_amount": Decimal("21.00"),
        "total_line": Decimal("121.00"),
    }
    defaults.update(kwargs)
    return InvoiceLine(**defaults)


def _make_valid_invoice(**kwargs) -> Invoice:
    line = _make_line()
    defaults = {
        "invoice_type": InvoiceType.STANDARD,
        "invoice_number": "F-001",
        "issue_date": date(2026, 3, 15),
        "issuer_name": "Acme SL",
        "issuer_cif": "A12345679",
        "issuer_address": "Calle Mayor 1",
        "recipient_name": "Client SA",
        "recipient_cif": "12345678Z",
        "lines": [line],
        "tax_breakdown": [],
        "subtotal": Decimal("100.00"),
        "total_iva": Decimal("21.00"),
        "total_amount": Decimal("121.00"),
        "source_file": "test.pdf",
        "extraction_confidence": 0.9,
    }
    defaults.update(kwargs)
    return Invoice(**defaults)


# ---- validate_irpf_amount ----

def test_irpf_amount_correct():
    inv = _make_valid_invoice(
        irpf_rate=Decimal("15"),
        irpf_amount=Decimal("15.00"),
        subtotal=Decimal("100.00"),
        total_amount=Decimal("106.00"),  # 121 - 15
    )
    issues = validate_irpf_amount(inv)
    assert issues == []


def test_irpf_amount_wrong():
    inv = _make_valid_invoice(
        irpf_rate=Decimal("15"),
        irpf_amount=Decimal("14.99"),
        subtotal=Decimal("100.00"),
        total_amount=Decimal("106.01"),
    )
    issues = validate_irpf_amount(inv)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].field == "irpf_amount"
    assert "14.99" in issues[0].message or "15.00" in issues[0].message


def test_irpf_rate_present_amount_missing():
    inv = _make_valid_invoice(
        irpf_rate=Decimal("15"),
        irpf_amount=None,
    )
    issues = validate_irpf_amount(inv)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].field == "irpf_amount"


def test_irpf_amount_present_rate_missing():
    inv = _make_valid_invoice(
        irpf_rate=None,
        irpf_amount=Decimal("15.00"),
    )
    issues = validate_irpf_amount(inv)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].field == "irpf_rate"


def test_irpf_both_none():
    inv = _make_valid_invoice(irpf_rate=None, irpf_amount=None)
    assert validate_irpf_amount(inv) == []


# ---- validate_total_recargo ----

def _make_recargo_line(line_number: int, base: str, rate: str, recargo: str) -> InvoiceLine:
    b = Decimal(base)
    r = Decimal(rate)
    rec = Decimal(recargo)
    iva_rate = Decimal("21")
    iva = b * iva_rate / 100
    total = b + iva + rec
    return InvoiceLine(
        line_number=line_number,
        description=f"Line {line_number}",
        base_amount=b,
        iva_rate=iva_rate,
        iva_amount=iva.quantize(Decimal("0.01")),
        recargo_equivalencia_rate=r,
        recargo_equivalencia_amount=rec,
        total_line=total.quantize(Decimal("0.01")),
    )


def test_total_recargo_sum_matches():
    line1 = _make_recargo_line(1, "100.00", "5.2", "5.20")
    line2 = _make_recargo_line(2, "100.00", "5.2", "5.20")
    inv = _make_valid_invoice(
        lines=[line1, line2],
        total_recargo=Decimal("10.40"),
        subtotal=Decimal("200.00"),
        total_iva=Decimal("42.00"),
        total_amount=Decimal("252.40"),
    )
    assert validate_total_recargo(inv) == []


def test_total_recargo_mismatch():
    line1 = _make_recargo_line(1, "100.00", "5.2", "5.20")
    inv = _make_valid_invoice(
        lines=[line1],
        total_recargo=Decimal("9.99"),
        subtotal=Decimal("100.00"),
        total_iva=Decimal("21.00"),
        total_amount=Decimal("131.19"),
    )
    issues = validate_total_recargo(inv)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].field == "total_recargo"


def test_total_recargo_missing_when_lines_have_it():
    line1 = _make_recargo_line(1, "100.00", "5.2", "5.20")
    inv = _make_valid_invoice(
        lines=[line1],
        total_recargo=None,
        subtotal=Decimal("100.00"),
        total_iva=Decimal("21.00"),
        total_amount=Decimal("121.00"),
    )
    issues = validate_total_recargo(inv)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "missing" in issues[0].message


# ---- validate_recargo_iva_pairs ----

def test_recargo_iva_pairs_21_5_2_correct():
    line = _make_line(
        iva_rate=Decimal("21"),
        recargo_equivalencia_rate=Decimal("5.2"),
        recargo_equivalencia_amount=Decimal("5.20"),
        iva_amount=Decimal("21.00"),
        total_line=Decimal("126.20"),
    )
    inv = _make_valid_invoice(lines=[line])
    assert validate_recargo_iva_pairs(inv) == []


def test_recargo_iva_pairs_10_1_4_correct():
    line = _make_line(
        iva_rate=Decimal("10"),
        iva_amount=Decimal("10.00"),
        recargo_equivalencia_rate=Decimal("1.4"),
        recargo_equivalencia_amount=Decimal("1.40"),
        total_line=Decimal("111.40"),
    )
    inv = _make_valid_invoice(lines=[line])
    assert validate_recargo_iva_pairs(inv) == []


def test_recargo_iva_pairs_wrong_rate():
    line = _make_line(
        iva_rate=Decimal("21"),
        iva_amount=Decimal("21.00"),
        recargo_equivalencia_rate=Decimal("1.4"),  # wrong: should be 5.2
        recargo_equivalencia_amount=Decimal("1.40"),
        total_line=Decimal("122.40"),
    )
    inv = _make_valid_invoice(lines=[line])
    issues = validate_recargo_iva_pairs(inv)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "5.2" in issues[0].message  # expected rate mentioned


def test_recargo_zero_iva_nonzero_recargo():
    line = _make_line(
        iva_rate=Decimal("0"),
        iva_amount=Decimal("0.00"),
        recargo_equivalencia_rate=Decimal("1.4"),
        recargo_equivalencia_amount=Decimal("1.40"),
        total_line=Decimal("101.40"),
    )
    inv = _make_valid_invoice(lines=[line])
    issues = validate_recargo_iva_pairs(inv)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "zero" in issues[0].message.lower()


# ---- validate_irpf_recargo_exclusivity ----

def test_irpf_recargo_both_present():
    line = _make_recargo_line(1, "100.00", "5.2", "5.20")
    inv = _make_valid_invoice(
        lines=[line],
        irpf_rate=Decimal("15"),
        irpf_amount=Decimal("15.00"),
        total_recargo=Decimal("5.20"),
        subtotal=Decimal("100.00"),
        total_iva=Decimal("21.00"),
        total_amount=Decimal("111.20"),
    )
    issues = validate_irpf_recargo_exclusivity(inv)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].field == "irpf_amount"


def test_irpf_recargo_only_irpf():
    inv = _make_valid_invoice(
        irpf_rate=Decimal("15"),
        irpf_amount=Decimal("15.00"),
        total_amount=Decimal("106.00"),
    )
    assert validate_irpf_recargo_exclusivity(inv) == []


# ---- validate_invoice integration ----

def test_validate_invoice_includes_new_checks():
    """validate_invoice() must surface irpf_amount errors from new validators."""
    inv = _make_valid_invoice(
        irpf_rate=Decimal("15"),
        irpf_amount=Decimal("14.99"),  # wrong: should be 15.00
        subtotal=Decimal("100.00"),
        total_amount=Decimal("106.01"),
    )
    result = validate_invoice(inv)
    fields = [i.field for i in result.issues]
    assert "irpf_amount" in fields
