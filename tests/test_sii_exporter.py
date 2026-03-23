"""Tests for SII/AEAT XML exporter."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

from backend.schemas.extraction import AnchorFields, ExtractionResult
from backend.services.sii_exporter import generate_sii_xml


def make_result(
    issuer_cif="B12345678",
    issuer_name="ACME SL",
    recipient_cif="A87654321",
    invoice_number="2024/001",
    issue_date="2024-01-15",
    base_imponible=Decimal("1000.00"),
    iva_rate=Decimal("21"),
    iva_amount=Decimal("210.00"),
    total_amount=Decimal("1210.00"),
) -> ExtractionResult:
    anchor = AnchorFields(
        issuer_cif=issuer_cif,
        issuer_name=issuer_name,
        recipient_cif=recipient_cif,
        invoice_number=invoice_number,
        issue_date=issue_date,
        base_imponible=base_imponible,
        iva_rate=iva_rate,
        iva_amount=iva_amount,
        total_amount=total_amount,
    )
    return ExtractionResult(
        anchor=anchor, discovered={}, issues=[], requires_review=False,
        llm_model="test", extraction_timestamp="2024-01-15T00:00:00",
    )


def test_sii_xml_is_valid_xml():
    xml_bytes, _ = generate_sii_xml(make_result(), "A12345678", "Test SA", "2024-01")
    root = ET.fromstring(xml_bytes)
    assert root is not None


def test_sii_xml_has_root_envelope():
    xml_bytes, _ = generate_sii_xml(make_result(), "A12345678", "Test SA", "2024-01")
    root = ET.fromstring(xml_bytes)
    assert "Envelope" in root.tag


def test_sii_xml_contains_titular():
    xml_bytes, _ = generate_sii_xml(make_result(), "A12345678", "Titular SA", "2024-01")
    xml_str = xml_bytes.decode("utf-8")
    assert "A12345678" in xml_str
    assert "Titular SA" in xml_str


def test_sii_xml_decimal_precision():
    xml_bytes, _ = generate_sii_xml(
        make_result(base_imponible=Decimal("1000.1"), iva_amount=Decimal("210.021")),
        "A12345678", "Test SA", "2024-01",
    )
    xml_str = xml_bytes.decode("utf-8")
    assert "1000.10" in xml_str
    assert "210.02" in xml_str


def test_sii_xml_utf8_encoding():
    xml_bytes, _ = generate_sii_xml(
        make_result(issuer_name="Empresa Ñoña SL"), "A12345678", "Test SA", "2024-01"
    )
    decoded = xml_bytes.decode("utf-8")
    assert "Ñoña" in decoded


def test_sii_xml_warnings_for_missing_fields():
    result = make_result(issuer_cif=None, invoice_number=None)
    _, warnings = generate_sii_xml(result, "A12345678", "Test SA", "2024-01")
    assert len(warnings) == 2
    warning_text = " ".join(warnings)
    assert "issuer CIF" in warning_text.lower() or "CIF" in warning_text
    assert "invoice number" in warning_text.lower() or "invoice" in warning_text.lower()
