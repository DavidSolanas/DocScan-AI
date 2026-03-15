# tests/test_invoice_validator.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.schemas.invoice import Invoice, InvoiceLine, InvoiceType
from backend.services.invoice_validator import (
    ValidationIssue,
    ValidationResult,
    validate_cif,
    validate_nie,
    validate_nif,
    validate_spanish_tax_id,
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
