# backend/schemas/extraction.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class AnchorFields:
    issuer_name: str | None = None
    issuer_cif: str | None = None
    recipient_name: str | None = None
    recipient_cif: str | None = None
    invoice_number: str | None = None
    issue_date: str | None = None       # ISO 8601 string
    base_imponible: Decimal | None = None
    iva_rate: Decimal | None = None
    iva_amount: Decimal | None = None
    irpf_rate: Decimal | None = None
    irpf_amount: Decimal | None = None
    total_amount: Decimal | None = None
    currency: str = "EUR"


@dataclass
class ExtractionIssue:
    field: str | None
    message: str
    severity: str   # "error" | "warning" | "observation"
    source: str     # "validator" | "llm"


@dataclass
class ExtractionResult:
    anchor: AnchorFields
    discovered: dict
    issues: list[ExtractionIssue]
    requires_review: bool
    llm_model: str
    extraction_timestamp: str

    @classmethod
    def from_dict(cls, d: dict) -> ExtractionResult:
        """Reconstruct from a JSON-decoded dict (Decimal fields stored as strings)."""
        def _dec(v: object) -> Decimal | None:
            return Decimal(str(v)) if v is not None else None

        anchor_raw = d.get("anchor") or {}
        anchor = AnchorFields(
            issuer_name=anchor_raw.get("issuer_name"),
            issuer_cif=anchor_raw.get("issuer_cif"),
            recipient_name=anchor_raw.get("recipient_name"),
            recipient_cif=anchor_raw.get("recipient_cif"),
            invoice_number=anchor_raw.get("invoice_number"),
            issue_date=anchor_raw.get("issue_date"),
            base_imponible=_dec(anchor_raw.get("base_imponible")),
            iva_rate=_dec(anchor_raw.get("iva_rate")),
            iva_amount=_dec(anchor_raw.get("iva_amount")),
            irpf_rate=_dec(anchor_raw.get("irpf_rate")),
            irpf_amount=_dec(anchor_raw.get("irpf_amount")),
            total_amount=_dec(anchor_raw.get("total_amount")),
            currency=anchor_raw.get("currency") or "EUR",
        )
        raw_issues = d.get("issues") or []
        issues = []
        for raw_i in raw_issues:
            try:
                issues.append(ExtractionIssue(**raw_i))
            except (TypeError, KeyError) as exc:
                raise ValueError(f"Malformed issue entry in ExtractionResult: {raw_i!r}") from exc
        return cls(
            anchor=anchor,
            discovered=d.get("discovered") or {},
            issues=issues,
            requires_review=bool(d.get("requires_review", False)),
            llm_model=d.get("llm_model") or "",
            extraction_timestamp=d.get("extraction_timestamp") or "",
        )
