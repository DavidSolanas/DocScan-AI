# backend/services/invoice_validator.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from backend.schemas.invoice import Invoice, InvoiceLine, InvoiceType


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: Literal["error", "warning"]


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue]
    requires_manual_review: bool


# --- NIF / CIF / NIE validation ---

_NIF_TABLE = "TRWAGMYFPDXBNJZSQVHLCKE"
_CIF_VALID_FIRST = "ABCDEFGHJNOPQRSTUVW"
_CIF_LETTER_ONLY_FIRST = "PQRSW"   # control char must be a letter
_CIF_DIGIT_ONLY_FIRST = "ABEH"     # control char must be a digit
_CIF_CONTROL_LETTERS = "JABCDEFGHI"


def validate_nif(value: str) -> bool:
    """Validate Spanish NIF: 8 digits + 1 check letter."""
    v = value.upper().strip()
    if len(v) != 9:
        return False
    if not v[:8].isdigit():
        return False
    if not v[8].isalpha():
        return False
    return v[8] == _NIF_TABLE[int(v[:8]) % 23]


def validate_nie(value: str) -> bool:
    """Validate Spanish NIE: X/Y/Z + 7 digits + 1 check letter."""
    v = value.upper().strip()
    if len(v) != 9:
        return False
    if v[0] not in "XYZ":
        return False
    mapping = {"X": "0", "Y": "1", "Z": "2"}
    return validate_nif(mapping[v[0]] + v[1:])


def validate_cif(value: str) -> bool:
    """Validate Spanish CIF: 1 org-type letter + 7 digits + 1 check char."""
    v = value.upper().strip()
    if len(v) != 9:
        return False
    if v[0] not in _CIF_VALID_FIRST:
        return False
    if not v[1:8].isdigit():
        return False

    digits = v[1:8]
    # Odd positions (1-indexed → 0-indexed: 0, 2, 4, 6)
    odd_sum = sum(int(digits[i]) for i in (0, 2, 4, 6))
    # Even positions (1-indexed → 0-indexed: 1, 3, 5) × 2, cross-sum if ≥ 10
    even_sum = 0
    for i in (1, 3, 5):
        d = int(digits[i]) * 2
        even_sum += d if d < 10 else d - 9

    control_digit = (10 - ((odd_sum + even_sum) % 10)) % 10
    control_letter = _CIF_CONTROL_LETTERS[control_digit]
    last = v[8]

    if v[0] in _CIF_LETTER_ONLY_FIRST:
        return last == control_letter
    elif v[0] in _CIF_DIGIT_ONLY_FIRST:
        return last == str(control_digit)
    else:
        return last in (control_letter, str(control_digit))


def validate_spanish_tax_id(value: str, field: str = "tax_id") -> ValidationIssue | None:
    """Validate a Spanish tax ID. Returns None if valid, ValidationIssue if not.

    Skips EU intracomunitario VAT codes (non-ES country prefix).
    """
    v = value.upper().strip()

    # Skip EU VAT codes like FR12345678901, DE123456789
    if v[:2].isalpha() and v[:2] != "ES":
        return None

    # Strip optional ES prefix
    if v.startswith("ES"):
        v = v[2:]

    if not v:
        return ValidationIssue(field=field, message="Empty tax ID", severity="error")

    if v[0] in "XYZ":
        valid = validate_nie(v)
        id_type = "NIE"
    elif v[0].isalpha():
        valid = validate_cif(v)
        id_type = "CIF"
    else:
        valid = validate_nif(v)
        id_type = "NIF"

    if not valid:
        return ValidationIssue(
            field=field,
            message=f"Invalid {id_type} checksum: {v}",
            severity="error",
        )
    return None


# --- Arithmetic validation ---

_EPSILON = Decimal("0.01")
_ROUNDING = ROUND_HALF_UP


def _round2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=_ROUNDING)


def validate_line_arithmetic(line: InvoiceLine) -> list[ValidationIssue]:
    """Check arithmetic on a single invoice line."""
    issues: list[ValidationIssue] = []

    if line.quantity is not None and line.unit_price is not None:
        discount = line.discount_pct if line.discount_pct is not None else Decimal("0")
        expected_base = _round2(line.quantity * line.unit_price * (1 - discount / 100))
        delta = abs(line.base_amount - expected_base)
        if delta >= _EPSILON:
            issues.append(ValidationIssue(
                field=f"lines[{line.line_number}].base_amount",
                message=f"base_amount mismatch: expected {expected_base}, got {line.base_amount}, delta={delta}",
                severity="error",
            ))

    expected_iva = _round2(line.base_amount * line.iva_rate / 100)
    delta = abs(line.iva_amount - expected_iva)
    if delta >= _EPSILON:
        issues.append(ValidationIssue(
            field=f"lines[{line.line_number}].iva_amount",
            message=f"iva_amount mismatch: expected {expected_iva}, got {line.iva_amount}, delta={delta}",
            severity="error",
        ))

    if line.recargo_equivalencia_rate is not None:
        expected_recargo = _round2(line.base_amount * line.recargo_equivalencia_rate / 100)
        actual_recargo = line.recargo_equivalencia_amount or Decimal("0")
        delta = abs(actual_recargo - expected_recargo)
        if delta >= _EPSILON:
            issues.append(ValidationIssue(
                field=f"lines[{line.line_number}].recargo_equivalencia_amount",
                message=f"recargo mismatch: expected {expected_recargo}, got {actual_recargo}, delta={delta}",
                severity="error",
            ))

    recargo = line.recargo_equivalencia_amount or Decimal("0")
    expected_total = _round2(line.base_amount + line.iva_amount + recargo)
    delta = abs(line.total_line - expected_total)
    if delta >= _EPSILON:
        issues.append(ValidationIssue(
            field=f"lines[{line.line_number}].total_line",
            message=f"total_line mismatch: expected {expected_total}, got {line.total_line}, delta={delta}",
            severity="error",
        ))

    return issues


def validate_totals(invoice: Invoice) -> list[ValidationIssue]:
    """Check invoice-level totals against line sums."""
    issues: list[ValidationIssue] = []

    expected_subtotal = _round2(sum((line.base_amount for line in invoice.lines), Decimal("0")))
    delta = abs(invoice.subtotal - expected_subtotal)
    if delta >= _EPSILON:
        issues.append(ValidationIssue(
            field="subtotal",
            message=f"subtotal mismatch: expected {expected_subtotal}, got {invoice.subtotal}, delta={delta}",
            severity="error",
        ))

    expected_iva = _round2(sum((line.iva_amount for line in invoice.lines), Decimal("0")))
    delta = abs(invoice.total_iva - expected_iva)
    if delta >= _EPSILON:
        issues.append(ValidationIssue(
            field="total_iva",
            message=f"total_iva mismatch: expected {expected_iva}, got {invoice.total_iva}, delta={delta}",
            severity="error",
        ))

    recargo = invoice.total_recargo or Decimal("0")
    irpf = invoice.irpf_amount or Decimal("0")
    expected_total = _round2(invoice.subtotal + invoice.total_iva + recargo - irpf)
    delta = abs(invoice.total_amount - expected_total)
    if delta >= _EPSILON:
        issues.append(ValidationIssue(
            field="total_amount",
            message=f"total_amount mismatch: expected {expected_total}, got {invoice.total_amount}, delta={delta}",
            severity="error",
        ))

    return issues


def validate_mandatory_fields(invoice: Invoice) -> list[ValidationIssue]:
    """Check RD 1619/2012 mandatory fields by invoice type."""
    issues: list[ValidationIssue] = []

    _sentinel = "[extraction_failed]"

    def _missing(val: object) -> bool:
        return val is None or val == "" or val == _sentinel

    if invoice.invoice_type == InvoiceType.SIMPLIFIED:
        for fname, val in [
            ("invoice_number", invoice.invoice_number),
            ("issue_date", invoice.issue_date),
            ("issuer_cif", invoice.issuer_cif),
            ("total_amount", invoice.total_amount),
        ]:
            if _missing(val):
                issues.append(ValidationIssue(field=fname, message=f"Mandatory field missing: {fname}", severity="error"))

        if invoice.total_amount > Decimal("400") and not invoice.recipient_cif:
            issues.append(ValidationIssue(
                field="recipient_cif",
                message="SIMPLIFIED invoice > €400 requires recipient_cif",
                severity="warning",
            ))
    else:
        for fname, val in [
            ("invoice_number", invoice.invoice_number),
            ("issue_date", invoice.issue_date),
            ("issuer_name", invoice.issuer_name),
            ("issuer_cif", invoice.issuer_cif),
            ("issuer_address", invoice.issuer_address),
            ("recipient_name", invoice.recipient_name),
            ("recipient_cif", invoice.recipient_cif),
            ("total_amount", invoice.total_amount),
        ]:
            if _missing(val):
                issues.append(ValidationIssue(field=fname, message=f"Mandatory field missing: {fname}", severity="error"))

    if invoice.invoice_type == InvoiceType.RECTIFICATIVE:
        if not invoice.original_invoice_ref:
            issues.append(ValidationIssue(field="original_invoice_ref", message="RECTIFICATIVE requires original_invoice_ref", severity="error"))
        if not invoice.rectification_reason:
            issues.append(ValidationIssue(field="rectification_reason", message="RECTIFICATIVE requires rectification_reason", severity="error"))

    return issues


def validate_invoice(invoice: Invoice) -> ValidationResult:
    """Run all validation checks and return aggregate result."""
    issues: list[ValidationIssue] = []

    _sentinel = "[extraction_failed]"
    if invoice.issuer_cif and invoice.issuer_cif not in ("", _sentinel):
        if issue := validate_spanish_tax_id(invoice.issuer_cif, "issuer_cif"):
            issues.append(issue)
    if invoice.recipient_cif and invoice.recipient_cif not in ("", _sentinel):
        if issue := validate_spanish_tax_id(invoice.recipient_cif, "recipient_cif"):
            issues.append(issue)

    for line in invoice.lines:
        issues.extend(validate_line_arithmetic(line))

    issues.extend(validate_totals(invoice))
    issues.extend(validate_mandatory_fields(invoice))

    errors = [i for i in issues if i.severity == "error"]
    critical_fields = {"invoice_number", "issuer_cif", "recipient_cif", "total_amount", "issue_date"}
    review_needed = any(i.field in critical_fields for i in issues)

    return ValidationResult(
        valid=len(errors) == 0,
        issues=issues,
        requires_manual_review=review_needed,
    )
