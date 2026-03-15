# backend/schemas/invoice.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, List, Optional

from pydantic import BaseModel, PlainSerializer

# Annotated type that serializes Decimal as string in JSON output.
# Pydantic v2's json_encoders config does not apply to model_dump_json(),
# so PlainSerializer via Annotated is the reliable approach.
# IMPORTANT: PlainSerializer applies to ALL serialization modes, not just JSON.
# model_dump() also returns str for these fields (not Decimal).
# Always use attribute access (invoice.field) for arithmetic — never model_dump().
DecimalStr = Annotated[Decimal, PlainSerializer(lambda x: str(x), return_type=str)]


class InvoiceType(str, Enum):
    STANDARD = "STANDARD"
    SIMPLIFIED = "SIMPLIFIED"
    RECTIFICATIVE = "RECTIFICATIVE"
    PROFORMA = "PROFORMA"
    SELF_BILLING = "SELF_BILLING"
    CREDIT_NOTE = "CREDIT_NOTE"
    PURCHASE = "PURCHASE"


class InvoiceLine(BaseModel):
    line_number: int
    description: str
    quantity: Optional[DecimalStr] = None
    unit: Optional[str] = None
    unit_price: Optional[DecimalStr] = None
    discount_pct: Optional[DecimalStr] = None
    discount_amount: Optional[DecimalStr] = None
    base_amount: DecimalStr
    iva_rate: DecimalStr
    iva_amount: DecimalStr
    recargo_equivalencia_rate: Optional[DecimalStr] = None
    recargo_equivalencia_amount: Optional[DecimalStr] = None
    total_line: DecimalStr


class TaxBreakdown(BaseModel):
    iva_rate: DecimalStr
    taxable_base: DecimalStr
    iva_amount: DecimalStr
    recargo_rate: Optional[DecimalStr] = None
    recargo_amount: Optional[DecimalStr] = None


class Invoice(BaseModel):
    # Identity
    invoice_type: InvoiceType
    invoice_number: str
    invoice_series: Optional[str] = None
    issue_date: date
    service_date: Optional[date] = None
    due_date: Optional[date] = None

    # Issuer
    issuer_name: str
    issuer_cif: str
    issuer_address: Optional[str] = None
    issuer_postal_code: Optional[str] = None
    issuer_city: Optional[str] = None
    issuer_province: Optional[str] = None
    issuer_country: str = "ES"
    issuer_phone: Optional[str] = None
    issuer_email: Optional[str] = None
    issuer_iban: Optional[str] = None

    # Recipient
    recipient_name: str
    recipient_cif: str
    recipient_address: Optional[str] = None
    recipient_postal_code: Optional[str] = None
    recipient_city: Optional[str] = None
    recipient_province: Optional[str] = None
    recipient_country: str = "ES"

    # Lines & tax
    lines: List[InvoiceLine]
    tax_breakdown: List[TaxBreakdown]

    # Totals
    subtotal: DecimalStr
    total_iva: DecimalStr
    total_recargo: Optional[DecimalStr] = None
    irpf_rate: Optional[DecimalStr] = None
    irpf_amount: Optional[DecimalStr] = None
    total_amount: DecimalStr
    currency: str = "EUR"

    # Payment
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None
    iban: Optional[str] = None
    swift_bic: Optional[str] = None

    # Cross-references
    po_number: Optional[str] = None
    delivery_note_number: Optional[str] = None
    original_invoice_ref: Optional[str] = None
    rectification_reason: Optional[str] = None

    # Metadata
    notes: Optional[str] = None
    language: str = "es"
    source_file: str
    extraction_confidence: float
    requires_manual_review: bool = False
    review_reasons: List[str] = []
