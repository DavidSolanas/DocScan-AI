"""FacturaE 3.2.2 XML export — Spanish e-invoice standard."""
from __future__ import annotations

import io
import uuid
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.schemas.extraction import ExtractionResult

_NS_FE = "http://www.facturae.es/Facturae/2009/v3.2/Facturae"
_NS_DS = "http://www.w3.org/2000/09/xmldsig#"

ET.register_namespace("fe", _NS_FE)
ET.register_namespace("ds", _NS_DS)


def _fmt(v: Decimal | None, default: str = "0.00") -> str:
    if v is None:
        return default
    return f"{v:.2f}"


def _person_type_code(tax_id: str | None) -> str:
    """Return "F" (natural person) or "J" (legal entity) from Spanish tax ID format."""
    if not tax_id:
        return "J"
    first = tax_id[0].upper()
    # NIF: starts with digit; NIE: starts with X/Y/Z; special NIF: K/L/M → natural person
    if first.isdigit() or first in ("X", "Y", "Z", "K", "L", "M"):
        return "F"
    return "J"  # CIF: starts with A-W (excluding X,Y,Z,K,L,M) → legal entity


def generate_facturae_xml(result: ExtractionResult) -> bytes:
    """Generate FacturaE 3.2.2 XML from an ExtractionResult."""
    a = result.anchor
    fe = f"{{{_NS_FE}}}"

    invoice_number = a.invoice_number or uuid.uuid4().hex[:8].upper()
    total_amount = _fmt(a.total_amount)
    base_imponible = _fmt(a.base_imponible)
    iva_rate = _fmt(a.iva_rate)
    iva_amount = _fmt(a.iva_amount)
    irpf_amount = _fmt(a.irpf_amount)
    issue_date = a.issue_date or date.today().isoformat()

    # Root
    root = ET.Element(f"{fe}Facturae")

    # FileHeader
    header = ET.SubElement(root, f"{fe}FileHeader")
    ET.SubElement(header, f"{fe}SchemaVersion").text = "3.2.2"
    ET.SubElement(header, f"{fe}Modality").text = "I"
    ET.SubElement(header, f"{fe}InvoiceIssuerType").text = "EM"

    batch = ET.SubElement(header, f"{fe}Batch")
    ET.SubElement(batch, f"{fe}BatchIdentifier").text = invoice_number
    ET.SubElement(batch, f"{fe}InvoicesCount").text = "1"
    total_inv = ET.SubElement(batch, f"{fe}TotalInvoicesAmount")
    ET.SubElement(total_inv, f"{fe}TotalAmount").text = total_amount
    total_out = ET.SubElement(batch, f"{fe}TotalOutstandingAmount")
    ET.SubElement(total_out, f"{fe}TotalAmount").text = total_amount
    total_exec = ET.SubElement(batch, f"{fe}TotalExecutableAmount")
    ET.SubElement(total_exec, f"{fe}TotalAmount").text = total_amount
    ET.SubElement(batch, f"{fe}InvoiceCurrencyCode").text = "EUR"

    # Parties
    parties = ET.SubElement(root, f"{fe}Parties")

    seller = ET.SubElement(parties, f"{fe}SellerParty")
    seller_tax = ET.SubElement(seller, f"{fe}TaxIdentification")
    ET.SubElement(seller_tax, f"{fe}PersonTypeCode").text = _person_type_code(a.issuer_cif)
    ET.SubElement(seller_tax, f"{fe}ResidenceTypeCode").text = "R"
    ET.SubElement(seller_tax, f"{fe}TaxIdentificationNumber").text = a.issuer_cif or ""
    seller_legal = ET.SubElement(seller, f"{fe}LegalEntity")
    ET.SubElement(seller_legal, f"{fe}CorporateName").text = a.issuer_name or ""

    buyer = ET.SubElement(parties, f"{fe}BuyerParty")
    buyer_tax = ET.SubElement(buyer, f"{fe}TaxIdentification")
    ET.SubElement(buyer_tax, f"{fe}PersonTypeCode").text = _person_type_code(a.recipient_cif)
    ET.SubElement(buyer_tax, f"{fe}ResidenceTypeCode").text = "R"
    ET.SubElement(buyer_tax, f"{fe}TaxIdentificationNumber").text = a.recipient_cif or ""
    buyer_legal = ET.SubElement(buyer, f"{fe}LegalEntity")
    ET.SubElement(buyer_legal, f"{fe}CorporateName").text = a.recipient_name or ""

    # Invoices
    invoices = ET.SubElement(root, f"{fe}Invoices")
    invoice = ET.SubElement(invoices, f"{fe}Invoice")

    inv_header = ET.SubElement(invoice, f"{fe}InvoiceHeader")
    ET.SubElement(inv_header, f"{fe}InvoiceNumber").text = invoice_number
    ET.SubElement(inv_header, f"{fe}InvoiceSeriesCode")
    ET.SubElement(inv_header, f"{fe}InvoiceDocumentType").text = "FC"
    ET.SubElement(inv_header, f"{fe}InvoiceClass").text = "OO"

    issue_data = ET.SubElement(invoice, f"{fe}InvoiceIssueData")
    ET.SubElement(issue_data, f"{fe}IssueDate").text = issue_date
    ET.SubElement(issue_data, f"{fe}InvoiceCurrencyCode").text = "EUR"
    ET.SubElement(issue_data, f"{fe}TaxCurrencyCode").text = "EUR"
    ET.SubElement(issue_data, f"{fe}Language").text = "es"

    # TaxesOutputs (IVA)
    taxes_out = ET.SubElement(invoice, f"{fe}TaxesOutputs")
    tax = ET.SubElement(taxes_out, f"{fe}Tax")
    ET.SubElement(tax, f"{fe}TaxTypeCode").text = "01"
    ET.SubElement(tax, f"{fe}TaxRate").text = iva_rate
    taxable = ET.SubElement(tax, f"{fe}TaxableBase")
    ET.SubElement(taxable, f"{fe}TotalAmount").text = base_imponible
    tax_amount = ET.SubElement(tax, f"{fe}TaxAmount")
    ET.SubElement(tax_amount, f"{fe}TotalAmount").text = iva_amount

    # InvoiceTotals
    totals = ET.SubElement(invoice, f"{fe}InvoiceTotals")
    ET.SubElement(totals, f"{fe}TotalGrossAmount").text = base_imponible
    ET.SubElement(totals, f"{fe}TotalGeneralDiscounts").text = "0.00"
    ET.SubElement(totals, f"{fe}TotalGeneralSurcharges").text = "0.00"
    ET.SubElement(totals, f"{fe}TotalGrossAmountBeforeTaxes").text = base_imponible
    ET.SubElement(totals, f"{fe}TotalTaxOutputs").text = iva_amount
    ET.SubElement(totals, f"{fe}TotalTaxesWithheld").text = irpf_amount
    ET.SubElement(totals, f"{fe}InvoiceTotal").text = total_amount
    ET.SubElement(totals, f"{fe}TotalOutstandingAmount").text = total_amount
    ET.SubElement(totals, f"{fe}TotalExecutableAmount").text = total_amount

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()
