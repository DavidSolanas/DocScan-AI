from __future__ import annotations
from decimal import Decimal
import pytest
from backend.schemas.extraction import AnchorFields
from backend.services.anchor_validator import AnchorValidator


def _anchor(**kwargs) -> AnchorFields:
    defaults = dict(
        issuer_name=None, issuer_cif=None, recipient_name=None, recipient_cif=None,
        invoice_number=None, issue_date=None, base_imponible=None, iva_rate=None,
        iva_amount=None, irpf_rate=None, irpf_amount=None, total_amount=None, currency="EUR",
    )
    return AnchorFields(**{**defaults, **kwargs})


def test_valid_nif_no_issue():
    # A12345679 is a known-valid NIF used in existing tests
    anchor = _anchor(issuer_cif="A12345679")
    issues = AnchorValidator().validate(anchor)
    assert not any(i.field == "issuer_cif" for i in issues)


def test_invalid_cif_produces_error():
    anchor = _anchor(issuer_cif="A12345670")  # bad checksum
    issues = AnchorValidator().validate(anchor)
    errors = [i for i in issues if i.field == "issuer_cif" and i.severity == "error"]
    assert len(errors) == 1


def test_cif_with_dash_is_cleaned_before_check():
    # Invoices often include dashes: "A-12345679" — strip before validating
    anchor = _anchor(issuer_cif="A-12345679")  # dash removed, valid CIF
    issues = AnchorValidator().validate(anchor)
    assert not any(i.field == "issuer_cif" for i in issues)


def test_cif_with_spaces_is_cleaned_before_check():
    # Some OCR outputs include spaces: "A 12345679" — strip before validating
    anchor = _anchor(issuer_cif="A 12345679")  # space removed, valid CIF
    issues = AnchorValidator().validate(anchor)
    assert not any(i.field == "issuer_cif" for i in issues)


def test_none_cif_no_issue():
    anchor = _anchor(issuer_cif=None)
    issues = AnchorValidator().validate(anchor)
    assert not any(i.field == "issuer_cif" for i in issues)


def test_valid_iva_arithmetic_no_issue():
    # 102.57 × 21% = 21.5397 → rounds to 21.54
    anchor = _anchor(
        base_imponible=Decimal("102.57"),
        iva_rate=Decimal("21"),
        iva_amount=Decimal("21.54"),
    )
    issues = AnchorValidator().validate(anchor)
    assert not any(i.field == "iva_amount" for i in issues)


def test_invalid_iva_produces_error():
    anchor = _anchor(
        base_imponible=Decimal("102.57"),
        iva_rate=Decimal("21"),
        iva_amount=Decimal("22.00"),  # wrong
    )
    issues = AnchorValidator().validate(anchor)
    errors = [i for i in issues if i.field == "iva_amount" and i.severity == "error"]
    assert len(errors) == 1


def test_iva_missing_fields_skipped():
    # If any iva field is None, skip the check — no false positives
    anchor = _anchor(base_imponible=Decimal("100"), iva_rate=None, iva_amount=Decimal("21"))
    issues = AnchorValidator().validate(anchor)
    assert not any(i.field == "iva_amount" for i in issues)


def test_valid_total_no_issue():
    anchor = _anchor(
        base_imponible=Decimal("102.57"),
        iva_amount=Decimal("21.54"),
        total_amount=Decimal("124.11"),
    )
    issues = AnchorValidator().validate(anchor)
    assert not any(i.field == "total_amount" for i in issues)


def test_invalid_total_produces_error():
    anchor = _anchor(
        base_imponible=Decimal("102.57"),
        iva_amount=Decimal("21.54"),
        total_amount=Decimal("130.00"),  # wrong
    )
    issues = AnchorValidator().validate(anchor)
    errors = [i for i in issues if i.field == "total_amount" and i.severity == "error"]
    assert len(errors) == 1


def test_total_with_irpf():
    # total = base + iva - irpf = 100 + 21 - 15 = 106
    anchor = _anchor(
        base_imponible=Decimal("100.00"),
        iva_amount=Decimal("21.00"),
        irpf_amount=Decimal("15.00"),
        total_amount=Decimal("106.00"),
    )
    issues = AnchorValidator().validate(anchor)
    assert not any(i.field == "total_amount" for i in issues)


def test_all_none_no_crash():
    anchor = _anchor()
    issues = AnchorValidator().validate(anchor)
    assert isinstance(issues, list)
    assert len(issues) == 0


def test_multi_rate_iva_skipped_when_observation_hints():
    # IVA arithmetic would fail (21% of 200 = 42, not 50) but LLM says mixed rates
    anchor = _anchor(
        base_imponible=Decimal("200.00"),
        iva_rate=Decimal("21"),
        iva_amount=Decimal("50.00"),  # would fail single-rate check
    )
    issues = AnchorValidator().validate(
        anchor,
        observations=["múltiples tipos de IVA detectados: 21% y 10%"],
    )
    assert not any(i.field == "iva_amount" for i in issues)
