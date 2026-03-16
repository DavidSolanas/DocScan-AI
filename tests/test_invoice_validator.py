# tests/test_invoice_validator.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.schemas.invoice import Invoice, InvoiceLine, InvoiceType
from backend.services.invoice_validator import (
    ValidationIssue,
    ValidationResult,
    validate_cif,
    validate_invoice,
    validate_line_arithmetic,
    validate_mandatory_fields,
    validate_nie,
    validate_nif,
    validate_spanish_tax_id,
    validate_totals,
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
        "issuer_cif": "A12345679",   # valid CIF
        "issuer_address": "Calle Mayor 1",
        "recipient_name": "Client SA",
        "recipient_cif": "12345678Z",  # valid NIF
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


# ---- NIF tests ----

def test_validate_nif_valid():
    # 12345678 % 23 = 14 → table[14] = "Z"
    assert validate_nif("12345678Z") is True


def test_validate_nif_wrong_check_letter():
    assert validate_nif("12345678A") is False


def test_validate_nif_ocr_confusion_zero_to_O():
    # Digit "0" OCR'd as letter "O" → non-digit in digit position
    assert validate_nif("1234567OZ") is False


def test_validate_nif_ocr_confusion_one_to_I():
    assert validate_nif("I2345678Z") is False


def test_validate_nif_ocr_confusion_five_to_S():
    assert validate_nif("1234S678A") is False


def test_validate_nif_ocr_confusion_eight_to_B():
    assert validate_nif("1234567BZ") is False


# ---- CIF tests ----

def test_validate_cif_valid_digit_control():
    # "A" type → digit control. Digits "1234567" → control_digit=9 → "A12345679"
    assert validate_cif("A12345679") is True


def test_validate_cif_invalid_check():
    assert validate_cif("A12345670") is False


def test_validate_cif_ocr_confusion_B_to_eight():
    # First letter "B" OCR'd as "8" → "8" not in valid CIF first letters
    assert validate_cif("812345679") is False


def test_validate_cif_invalid_first_letter():
    assert validate_cif("I12345679") is False


def test_validate_cif_non_digits_in_body():
    assert validate_cif("AO2345679") is False


# ---- NIE tests ----

def test_validate_nie_valid_x():
    # X→0, "00000000" % 23 = 0 → table[0] = "T"
    assert validate_nie("X0000000T") is True


def test_validate_nie_invalid_check():
    assert validate_nie("X0000000A") is False


def test_validate_nie_invalid_prefix():
    assert validate_nie("A0000000T") is False


# ---- validate_spanish_tax_id ----

def test_validate_spanish_tax_id_valid_nif():
    assert validate_spanish_tax_id("12345678Z", "issuer_cif") is None


def test_validate_spanish_tax_id_invalid_nif_returns_issue():
    issue = validate_spanish_tax_id("12345678A", "issuer_cif")
    assert issue is not None
    assert issue.severity == "error"
    assert "NIF" in issue.message
    assert issue.field == "issuer_cif"


def test_validate_spanish_tax_id_valid_cif():
    assert validate_spanish_tax_id("A12345679", "issuer_cif") is None


def test_validate_spanish_tax_id_invalid_cif():
    issue = validate_spanish_tax_id("A12345670", "issuer_cif")
    assert issue is not None
    assert "CIF" in issue.message


def test_validate_spanish_tax_id_eu_vat_skipped():
    # EU intracomunitario — no Spanish checksum applies
    assert validate_spanish_tax_id("FR12345678901", "issuer_cif") is None


def test_validate_spanish_tax_id_es_prefix_stripped():
    assert validate_spanish_tax_id("ES12345678Z", "issuer_cif") is None


# ---- validate_line_arithmetic ----

def test_validate_line_arithmetic_exact_match():
    line = _make_line()
    assert validate_line_arithmetic(line) == []


def test_validate_line_arithmetic_iva_off_by_one_cent():
    line = _make_line(iva_amount=Decimal("20.99"))  # should be 21.00
    issues = validate_line_arithmetic(line)
    fields = {i.field for i in issues}
    assert "lines[1].iva_amount" in fields
    assert any("delta=0.01" in i.message for i in issues)


def test_validate_line_arithmetic_skips_base_when_quantity_none():
    line = _make_line(quantity=None, unit_price=Decimal("50.00"))
    issues = validate_line_arithmetic(line)
    assert not any("base_amount" in i.field for i in issues)


def test_validate_line_arithmetic_with_quantity_and_discount():
    # 2 × 60 × (1 - 10/100) = 108.00
    line = _make_line(
        quantity=Decimal("2"),
        unit_price=Decimal("60.00"),
        discount_pct=Decimal("10"),
        base_amount=Decimal("108.00"),
        iva_rate=Decimal("21"),
        iva_amount=Decimal("22.68"),
        total_line=Decimal("130.68"),
    )
    assert validate_line_arithmetic(line) == []


# ---- validate_totals ----

def test_validate_totals_correct():
    assert validate_totals(_make_valid_invoice()) == []


def test_validate_totals_subtotal_off():
    invoice = _make_valid_invoice(subtotal=Decimal("99.00"))
    issues = validate_totals(invoice)
    assert any(i.field == "subtotal" for i in issues)


def test_validate_totals_total_amount_off():
    invoice = _make_valid_invoice(total_amount=Decimal("120.00"))
    issues = validate_totals(invoice)
    assert any(i.field == "total_amount" for i in issues)


def test_validate_totals_with_irpf():
    # total = 100 + 21 - 15 = 106
    invoice = _make_valid_invoice(
        irpf_rate=Decimal("15"),
        irpf_amount=Decimal("15.00"),
        total_amount=Decimal("106.00"),
    )
    assert validate_totals(invoice) == []


# ---- validate_mandatory_fields ----

def test_validate_mandatory_standard_complete():
    assert validate_mandatory_fields(_make_valid_invoice()) == []


def test_validate_mandatory_standard_missing_issuer_address():
    invoice = _make_valid_invoice(issuer_address=None)
    issues = validate_mandatory_fields(invoice)
    assert any(i.field == "issuer_address" and i.severity == "error" for i in issues)


def test_validate_mandatory_simplified_no_recipient_ok():
    # SIMPLIFIED doesn't require recipient fields
    invoice = _make_valid_invoice(
        invoice_type=InvoiceType.SIMPLIFIED,
        issuer_address=None,
        recipient_name="[extraction_failed]",
    )
    issues = validate_mandatory_fields(invoice)
    assert not any(i.field == "recipient_name" for i in issues)
    assert not any(i.field == "issuer_address" for i in issues)


def test_validate_mandatory_simplified_warn_over_400():
    invoice = _make_valid_invoice(
        invoice_type=InvoiceType.SIMPLIFIED,
        recipient_cif="",
        total_amount=Decimal("500.00"),
        # need total_iva consistent; update subtotal/total_iva to match
        subtotal=Decimal("413.22"),
        total_iva=Decimal("86.78"),
    )
    issues = validate_mandatory_fields(invoice)
    assert any(i.field == "recipient_cif" and i.severity == "warning" for i in issues)


def test_validate_mandatory_rectificative_requires_extra_fields():
    invoice = _make_valid_invoice(invoice_type=InvoiceType.RECTIFICATIVE)
    issues = validate_mandatory_fields(invoice)
    fields = {i.field for i in issues}
    assert "original_invoice_ref" in fields
    assert "rectification_reason" in fields


# ---- validate_invoice (aggregate) ----

def test_validate_invoice_all_valid():
    result = validate_invoice(_make_valid_invoice())
    assert result.valid is True
    assert result.issues == []
    assert result.requires_manual_review is False


def test_validate_invoice_bad_cif_requires_review():
    invoice = _make_valid_invoice(issuer_cif="A12345670")  # bad checksum
    result = validate_invoice(invoice)
    assert result.valid is False
    assert result.requires_manual_review is True
    assert any(i.field == "issuer_cif" for i in result.issues)
