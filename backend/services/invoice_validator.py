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


# --- Arithmetic validation (stubs — filled in Task 4) ---

_EPSILON = Decimal("0.01")
_ROUNDING = ROUND_HALF_UP


def _round2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=_ROUNDING)


def validate_line_arithmetic(line: InvoiceLine) -> list[ValidationIssue]:
    raise NotImplementedError


def validate_totals(invoice: Invoice) -> list[ValidationIssue]:
    raise NotImplementedError


def validate_mandatory_fields(invoice: Invoice) -> list[ValidationIssue]:
    raise NotImplementedError


def validate_invoice(invoice: Invoice) -> ValidationResult:
    raise NotImplementedError
