# backend/services/invoice_extractor.py
from __future__ import annotations

import json
import logging
import re
import typing
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin

from backend.schemas.invoice import Invoice, InvoiceType
from backend.services.invoice_validator import ValidationResult, validate_invoice
from backend.services.llm_service import LLMError, LLMService

INVOICE_KEYWORDS = [
    "factura", "invoice", "nif", "cif", "iva", "vat",
    "base imponible", "receptor", "total",
]

_EXTRACTOR_SYSTEM = (
    "You are an invoice data extractor. Extract only the requested fields. "
    "Output valid JSON. Use null for missing fields."
)

_TYPE_PATTERN = re.compile(
    r"\b(STANDARD|SIMPLIFIED|RECTIFICATIVE|PROFORMA|SELF_BILLING|CREDIT_NOTE|PURCHASE)\b"
)


def is_likely_invoice(text: str) -> bool:
    """Return True if ≥3 invoice keywords found (case-insensitive)."""
    lower = text.lower()
    return sum(1 for kw in INVOICE_KEYWORDS if kw in lower) >= 3


async def classify_document(text: str, llm: LLMService) -> InvoiceType:
    prompt = (
        text[:500]
        + "\n\nClassify this invoice. Options: "
        "STANDARD, SIMPLIFIED, RECTIFICATIVE, PROFORMA, SELF_BILLING, CREDIT_NOTE, PURCHASE"
    )
    system = "You are a document classifier. Respond with exactly one word from the allowed list."
    response = await llm.complete(prompt, system=system, json_mode=False)
    match = _TYPE_PATTERN.search(response.upper())
    if match:
        return InvoiceType(match.group(1))
    return InvoiceType.STANDARD


async def extract_headers(text: str, doc_type: InvoiceType, llm: LLMService) -> dict:
    prompt = (
        text
        + "\n\nExtract as JSON with these fields: invoice_number, invoice_series, issue_date, "
        "service_date, due_date, issuer_name, issuer_cif, issuer_address, issuer_postal_code, "
        "issuer_city, issuer_country, recipient_name, recipient_cif, recipient_address, "
        "recipient_city, language."
    )
    return await llm.complete_json(prompt, system=_EXTRACTOR_SYSTEM)


async def extract_line_items(text: str, doc_type: InvoiceType, llm: LLMService) -> list[dict]:
    prompt = (
        text
        + "\n\nExtract all line items as a JSON array. Each item must have: "
        "line_number, description, quantity, unit, unit_price, discount_pct, "
        "base_amount, iva_rate, iva_amount, total_line. Use null for missing numeric fields."
    )
    raw = await llm.complete_json(prompt, system=_EXTRACTOR_SYSTEM)
    if isinstance(raw, list):
        return raw
    lines = raw.get("lines")
    if lines is None and raw:
        logging.getLogger(__name__).warning(
            "extract_line_items: expected 'lines' key but got keys %s; returning empty list",
            list(raw.keys()),
        )
        return []
    return lines or []


async def extract_totals(text: str, doc_type: InvoiceType, llm: LLMService) -> dict:
    prompt = (
        text
        + "\n\nExtract as JSON with these fields: subtotal, total_iva, total_recargo, "
        "irpf_rate, irpf_amount, total_amount, currency, payment_method, payment_reference, "
        "iban, po_number, original_invoice_ref, rectification_reason, notes."
    )
    return await llm.complete_json(prompt, system=_EXTRACTOR_SYSTEM)


def _is_optional_field(field_info: Any) -> bool:
    """Return True if the field annotation is Optional[X] (i.e., Union[X, None])."""
    ann = field_info.annotation
    origin = get_origin(ann)
    return origin is typing.Union and type(None) in get_args(ann)


def _default_for_annotation(ann: Any) -> Any:
    """Return a sensible default for a required field that failed extraction."""
    # Unwrap Annotated wrappers (e.g. DecimalStr = Annotated[Decimal, ...])
    if get_origin(ann) is typing.Annotated:
        ann = get_args(ann)[0]

    if isinstance(ann, type) and issubclass(ann, Enum):
        return list(ann)[0]  # first enum value as default
    if ann is str or ann == str:
        return "[extraction_failed]"
    if ann is date or ann == date:
        return date(2000, 1, 1)
    if ann is Decimal or ann == Decimal:
        return Decimal("0")
    if ann is float or ann == float:
        return 0.0
    if ann is int or ann == int:
        return 0
    if ann is bool or ann == bool:
        return False
    # Check for list/List types
    origin = get_origin(ann)
    if origin is list:
        return []
    # Fallback
    return "[extraction_failed]"


# Keys that must not be overwritten by LLM output
_PROTECTED_KEYS = {"invoice_type", "source_file", "extraction_confidence", "tax_breakdown"}


def _safe_merge(
    invoice_type: InvoiceType,
    headers: dict,
    lines_raw: list[dict],
    totals: dict,
    source_file: str,
) -> Invoice:
    """Merge dicts and build Invoice with partial-failure recovery."""
    from pydantic import ValidationError

    merged: dict[str, Any] = {
        "invoice_type": invoice_type,
        "source_file": source_file,
        "extraction_confidence": 0.7,
        "tax_breakdown": [],
        "lines": lines_raw,
    }
    merged.update({k: v for k, v in headers.items() if k not in _PROTECTED_KEYS})
    merged.update({k: v for k, v in totals.items() if k not in _PROTECTED_KEYS})

    review_reasons: list[str] = []

    try:
        return Invoice.model_validate(merged)
    except ValidationError as exc:
        for err in exc.errors():
            loc = err["loc"]
            field = str(loc[0]) if loc else "unknown"
            review_reasons.append(f"Field extraction failed: {field} — {err['msg']}")
            field_info = Invoice.model_fields.get(field)
            if field_info is not None and not _is_optional_field(field_info):
                # Required field: use type-appropriate default
                merged[field] = _default_for_annotation(field_info.annotation)
            else:
                merged[field] = None

        try:
            invoice = Invoice.model_validate(merged)
        except ValidationError as exc2:
            # Second pass: fill remaining failures with typed defaults
            for err in exc2.errors():
                loc = err["loc"]
                field = str(loc[0]) if loc else "unknown"
                review_reasons.append(f"Field extraction failed (pass 2): {field} — {err['msg']}")
                field_info = Invoice.model_fields.get(field)
                if field_info is not None and not _is_optional_field(field_info):
                    merged[field] = _default_for_annotation(field_info.annotation)
                else:
                    merged[field] = None
            try:
                invoice = Invoice.model_validate(merged)
            except ValidationError as exc:
                # Last resort: use absolute minimum defaults
                invoice = Invoice(
                    invoice_type=invoice_type,
                    invoice_number="[extraction_failed]",
                    issue_date=date(2000, 1, 1),
                    issuer_name="[extraction_failed]",
                    issuer_cif="[extraction_failed]",
                    recipient_name="[extraction_failed]",
                    recipient_cif="[extraction_failed]",
                    lines=[],
                    tax_breakdown=[],
                    subtotal=Decimal("0"),
                    total_iva=Decimal("0"),
                    total_amount=Decimal("0"),
                    source_file=source_file,
                    extraction_confidence=0.0,
                )
                review_reasons.append(f"Critical merge failure: {exc}")

        invoice.review_reasons = review_reasons
        invoice.requires_manual_review = bool(review_reasons)
        return invoice


async def extract_invoice(
    text: str,
    source_file: str,
    llm: LLMService,
) -> tuple[Invoice, ValidationResult]:
    """Run 5-pass extraction. Always returns a (partial) Invoice — never raises."""
    review_reasons: list[str] = []
    invoice_type = InvoiceType.STANDARD
    headers: dict = {}
    lines_raw: list[dict] = []
    totals: dict = {}

    try:
        invoice_type = await classify_document(text, llm)
    except LLMError as exc:
        review_reasons.append(f"Pass 1 (classify) failed: {exc}")

    try:
        headers = await extract_headers(text, invoice_type, llm)
    except LLMError as exc:
        review_reasons.append(f"Pass 2 (headers) failed: {exc}")

    try:
        lines_raw = await extract_line_items(text, invoice_type, llm)
    except LLMError as exc:
        review_reasons.append(f"Pass 3 (line items) failed: {exc}")
        lines_raw = []

    try:
        totals = await extract_totals(text, invoice_type, llm)
    except LLMError as exc:
        review_reasons.append(f"Pass 4 (totals) failed: {exc}")

    invoice = _safe_merge(invoice_type, headers, lines_raw, totals, source_file)
    invoice.review_reasons = review_reasons + invoice.review_reasons
    invoice.requires_manual_review = bool(invoice.review_reasons)

    result = validate_invoice(invoice)
    invoice.requires_manual_review = invoice.requires_manual_review or result.requires_manual_review
    invoice.review_reasons += [i.message for i in result.issues if i.severity == "error"]

    return invoice, result
