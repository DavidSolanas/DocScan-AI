from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from backend.config import get_settings
from backend.schemas.extraction import AnchorFields, ExtractionIssue, ExtractionResult
from backend.services.anchor_validator import AnchorValidator
from backend.services.llm_service import LLMParseError, LLMService, get_llm_service

MAX_TEXT_CHARS = 12_000

_SYSTEM_MSG = (
    "You are a document digitalization expert specializing in Spanish invoices. "
    "Extract information for legal and tax compliance (declaración de la renta, "
    "IVA returns, audits). Be thorough and accurate. "
    "Respond with valid JSON only — no markdown, no explanation."
)

_PROMPT_TEMPLATE = """\
[OCR TEXT]
{text}

---
Extract these CRITICAL fields (legally mandatory — infer if needed, null if truly absent):
- issuer_name, issuer_cif           (emisor / vendedor)
- recipient_name, recipient_cif      (receptor / comprador)
- invoice_number, issue_date         (número factura, fecha ISO 8601 YYYY-MM-DD)
- base_imponible, iva_rate, iva_amount
- irpf_rate, irpf_amount             (retención IRPF, null if absent)
- total_amount, currency             (total a pagar, default "EUR")

Also discover and include anything else relevant in "discovered":
line items, addresses, payment info, references, notes, etc.

Note any anomalies or inconsistencies in "llm_observations".

Respond with valid JSON only:
{{
  "anchor": {{ <critical fields above> }},
  "discovered": {{ <anything else> }},
  "llm_observations": ["<observation>"]
}}"""


class IntelligentExtractor:
    def __init__(self, llm: LLMService | None = None) -> None:
        self._llm = llm or get_llm_service()

    async def extract(self, text: str, filename: str) -> ExtractionResult:
        settings = get_settings()
        model = settings.OLLAMA_DEFAULT_MODEL

        truncated = len(text) > MAX_TEXT_CHARS
        text = text[:MAX_TEXT_CHARS]
        prompt = _PROMPT_TEMPLATE.format(text=text)

        try:
            raw = await self._llm.complete_json(prompt, system=_SYSTEM_MSG)
        except LLMParseError:
            return self._failure(model, "LLM parse failure — could not extract valid JSON")

        # Structural validation: must have a non-empty anchor dict
        if not isinstance(raw, dict) or not raw.get("anchor"):
            return self._failure(model, "LLM returned unexpected structure — anchor key missing or empty")

        anchor = self._parse_anchor(raw["anchor"])
        discovered = raw.get("discovered") if isinstance(raw.get("discovered"), dict) else {}
        observations = raw.get("llm_observations") if isinstance(raw.get("llm_observations"), list) else []

        issues = AnchorValidator().validate(anchor, discovered=discovered, observations=observations)

        for obs in observations:
            if isinstance(obs, str):
                issues.append(ExtractionIssue(field=None, message=obs, severity="observation", source="llm"))

        if truncated:
            issues.append(ExtractionIssue(
                field=None,
                message=f"OCR text truncated to {MAX_TEXT_CHARS:,} chars — later pages may be missing",
                severity="warning",
                source="validator",
            ))

        requires_review = any(i.severity == "error" for i in issues)

        return ExtractionResult(
            anchor=anchor,
            discovered=discovered or {},
            issues=issues,
            requires_review=requires_review,
            llm_model=model,
            extraction_timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def _failure(self, model: str, message: str) -> ExtractionResult:
        return ExtractionResult(
            anchor=AnchorFields(),
            discovered={},
            issues=[ExtractionIssue(field=None, message=message, severity="error", source="validator")],
            requires_review=True,
            llm_model=model,
            extraction_timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    @staticmethod
    def _parse_anchor(raw: dict) -> AnchorFields:
        def _dec(v: object) -> Decimal | None:
            if v is None:
                return None
            try:
                return Decimal(str(v))
            except InvalidOperation:
                return None

        def _str(v: object) -> str | None:
            return str(v).strip() or None if v else None

        return AnchorFields(
            issuer_name=_str(raw.get("issuer_name")),
            issuer_cif=_str(raw.get("issuer_cif")),
            recipient_name=_str(raw.get("recipient_name")),
            recipient_cif=_str(raw.get("recipient_cif")),
            invoice_number=_str(raw.get("invoice_number")),
            issue_date=_str(raw.get("issue_date")),
            base_imponible=_dec(raw.get("base_imponible")),
            iva_rate=_dec(raw.get("iva_rate")),
            iva_amount=_dec(raw.get("iva_amount")),
            irpf_rate=_dec(raw.get("irpf_rate")),
            irpf_amount=_dec(raw.get("irpf_amount")),
            total_amount=_dec(raw.get("total_amount")),
            currency=_str(raw.get("currency")) or "EUR",
        )
