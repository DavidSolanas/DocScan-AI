# backend/services/anchor_validator.py
from __future__ import annotations
from decimal import ROUND_HALF_UP, Decimal
from backend.schemas.extraction import AnchorFields, ExtractionIssue
from backend.services.invoice_validator import validate_spanish_tax_id

_EPSILON = Decimal("0.01")


class AnchorValidator:
    def validate(
        self,
        anchor: AnchorFields,
        discovered: dict | None = None,
        observations: list[str] | None = None,
    ) -> list[ExtractionIssue]:
        """Validate anchor fields. Pass `discovered` and `observations` from the LLM
        response so the IVA check can be skipped on multi-rate invoices."""
        issues: list[ExtractionIssue] = []
        self._check_tax_id(anchor.issuer_cif, "issuer_cif", issues)
        self._check_tax_id(anchor.recipient_cif, "recipient_cif", issues)
        self._check_iva(anchor, issues, discovered=discovered, observations=observations)
        self._check_total(anchor, issues)
        return issues

    def _check_tax_id(self, value: str | None, field: str, issues: list[ExtractionIssue]) -> None:
        if value is None:
            return
        clean = value.replace("-", "").replace(" ", "").upper()
        issue = validate_spanish_tax_id(clean, field=field)
        if issue is not None:
            issues.append(ExtractionIssue(
                field=field,
                message=issue.message,
                severity="error",
                source="validator",
            ))

    def _check_iva(
        self,
        anchor: AnchorFields,
        issues: list[ExtractionIssue],
        discovered: dict | None = None,
        observations: list[str] | None = None,
    ) -> None:
        if anchor.base_imponible is None or anchor.iva_rate is None or anchor.iva_amount is None:
            return
        # Skip single-rate check when the LLM indicates multiple IVA rates are present
        multi_rate_hints = ["múltiples tipos", "multiple iva", "varios tipos", "mixed iva", "tipo reducido y general"]
        all_text = " ".join((observations or [])).lower()
        discovered_str = str(discovered or {}).lower()
        if any(hint in all_text or hint in discovered_str for hint in multi_rate_hints):
            return
        expected = (anchor.base_imponible * anchor.iva_rate / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        delta = abs(expected - anchor.iva_amount)
        if delta >= _EPSILON:
            issues.append(ExtractionIssue(
                field="iva_amount",
                message=(
                    f"IVA mismatch: {anchor.base_imponible} × {anchor.iva_rate}% "
                    f"= {expected}, got {anchor.iva_amount} (Δ{delta})"
                ),
                severity="error",
                source="validator",
            ))

    def _check_total(self, anchor: AnchorFields, issues: list[ExtractionIssue]) -> None:
        if anchor.base_imponible is None or anchor.iva_amount is None or anchor.total_amount is None:
            return
        irpf = anchor.irpf_amount or Decimal("0")
        expected = (anchor.base_imponible + anchor.iva_amount - irpf).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        delta = abs(expected - anchor.total_amount)
        if delta >= _EPSILON:
            issues.append(ExtractionIssue(
                field="total_amount",
                message=(
                    f"Total mismatch: {anchor.base_imponible} + {anchor.iva_amount} "
                    f"- {irpf} = {expected}, got {anchor.total_amount} (Δ{delta})"
                ),
                severity="error",
                source="validator",
            ))
