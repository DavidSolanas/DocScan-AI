"""Tests for FacturaE 3.2.2 XML exporter."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

from backend.schemas.extraction import AnchorFields, ExtractionResult
from backend.services.facturae_exporter import generate_facturae_xml

_NS_FE = "http://www.facturae.es/Facturae/2009/v3.2/Facturae"


def make_result(
    issuer_cif="B12345678",
    issuer_name="ACME SL",
    recipient_cif="A87654321",
    recipient_name="XYZ SA",
    invoice_number="2024/001",
    issue_date="2024-01-15",
    base_imponible=Decimal("1000.00"),
    iva_rate=Decimal("21"),
    iva_amount=Decimal("210.00"),
    irpf_amount=None,
    total_amount=Decimal("1210.00"),
) -> ExtractionResult:
    anchor = AnchorFields(
        issuer_cif=issuer_cif,
        issuer_name=issuer_name,
        recipient_cif=recipient_cif,
        recipient_name=recipient_name,
        invoice_number=invoice_number,
        issue_date=issue_date,
        base_imponible=base_imponible,
        iva_rate=iva_rate,
        iva_amount=iva_amount,
        irpf_amount=irpf_amount,
        total_amount=total_amount,
    )
    return ExtractionResult(
        anchor=anchor, discovered={}, issues=[], requires_review=False,
        llm_model="test", extraction_timestamp="2024-01-15T00:00:00",
    )


def test_facturae_xml_is_valid_xml():
    xml_bytes = generate_facturae_xml(make_result())
    root = ET.fromstring(xml_bytes)
    assert root is not None


def test_facturae_root_is_facturae():
    xml_bytes = generate_facturae_xml(make_result())
    root = ET.fromstring(xml_bytes)
    assert "Facturae" in root.tag


def test_facturae_seller_party_mapping():
    xml_bytes = generate_facturae_xml(make_result())
    root = ET.fromstring(xml_bytes)
    seller = root.find(f".//{{{_NS_FE}}}SellerParty")
    assert seller is not None
    cif_el = seller.find(f".//{{{_NS_FE}}}TaxIdentificationNumber")
    assert cif_el is not None and cif_el.text == "B12345678"
    name_el = seller.find(f".//{{{_NS_FE}}}CorporateName")
    assert name_el is not None and name_el.text == "ACME SL"


def test_facturae_buyer_party_mapping():
    xml_bytes = generate_facturae_xml(make_result())
    root = ET.fromstring(xml_bytes)
    buyer = root.find(f".//{{{_NS_FE}}}BuyerParty")
    assert buyer is not None
    cif_el = buyer.find(f".//{{{_NS_FE}}}TaxIdentificationNumber")
    assert cif_el is not None and cif_el.text == "A87654321"
    name_el = buyer.find(f".//{{{_NS_FE}}}CorporateName")
    assert name_el is not None and name_el.text == "XYZ SA"


def test_facturae_iva_tax_element():
    xml_bytes = generate_facturae_xml(make_result())
    root = ET.fromstring(xml_bytes)
    taxes_out = root.find(f".//{{{_NS_FE}}}TaxesOutputs")
    assert taxes_out is not None
    tax = taxes_out.find(f"{{{_NS_FE}}}Tax")
    assert tax is not None
    rate_el = tax.find(f"{{{_NS_FE}}}TaxRate")
    assert rate_el is not None and rate_el.text == "21.00"
    taxable = tax.find(f".//{{{_NS_FE}}}TaxableBase/{{{_NS_FE}}}TotalAmount")
    assert taxable is not None and taxable.text == "1000.00"


def test_facturae_irpf_not_in_outputs():
    """IRPF is a withheld tax — should appear in TotalTaxesWithheld, not TaxesOutputs."""
    xml_bytes = generate_facturae_xml(make_result(irpf_amount=Decimal("150.00")))
    root = ET.fromstring(xml_bytes)
    totals = root.find(f".//{{{_NS_FE}}}InvoiceTotals")
    assert totals is not None
    withheld = totals.find(f"{{{_NS_FE}}}TotalTaxesWithheld")
    assert withheld is not None and withheld.text == "150.00"
    # IVA output taxes (TaxesOutputs) should not contain IRPF
    taxes_out = root.find(f".//{{{_NS_FE}}}TaxesOutputs")
    assert taxes_out is not None
    # IRPF appears in withheld, not as a Tax element in TaxesOutputs
    for tax in taxes_out.findall(f"{{{_NS_FE}}}Tax"):
        type_code = tax.find(f"{{{_NS_FE}}}TaxTypeCode")
        # Tax type "04" is IRPF in FacturaE — should not appear here
        assert type_code is None or type_code.text != "04"
