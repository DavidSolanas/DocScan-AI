from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from backend.config import get_settings
from backend.schemas.extraction import AnchorFields, ExtractionIssue, ExtractionResult
from backend.services.anchor_validator import AnchorValidator
from backend.services.llm_service import LLMParseError, LLMService, LLMTimeoutError, get_llm_service

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
Please extract the following information from the document. The document is likely in Spanish.
This is not a rigid schema but a guide to extract all relevant legal and financial information.

Map the core information to these CRITICAL fields (legally mandatory — infer if needed, null if truly absent):
- issuer_name, issuer_cif           (emisor / vendedor, NIF/CIF/DNI)
- recipient_name, recipient_cif      (receptor / comprador / cliente, NIF/CIF/DNI)
- invoice_number, issue_date         (número de factura, fecha ISO 8601 YYYY-MM-DD)
- base_imponible, iva_rate, iva_amount (base imponible, % IVA, cuota IVA)
- irpf_rate, irpf_amount             (retención IRPF, null if absent)
- total_amount, currency             (total a pagar, default "EUR")

Also discover and include ANYTHING ELSE relevant in the "discovered" object:
line items (conceptos), addresses (direcciones), payment info (forma de pago, IBAN), references, notes, etc.
Extract as much structured detail as possible into "discovered".

Note any anomalies or inconsistencies in "llm_observations".

Respond with valid JSON only:
{{
  "anchor": {{ <critical fields above> }},
  "discovered": {{ <all other extracted information as structured key-value pairs> }},
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
        except LLMTimeoutError:
            return self._failure(model, "LLM timed out — model took too long to respond")
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
                message=f"OCR text for '{filename}' truncated to {MAX_TEXT_CHARS:,} chars — later pages may be missing",
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

    _FIELD_DESCRIPTIONS: dict[str, str] = {
        "anchor.invoice_number": "Invoice number (número de factura)",
        "anchor.issuer_cif": "Issuer NIF/CIF (NIF/CIF del emisor/vendedor)",
        "anchor.issuer_name": "Issuer company name (nombre del emisor)",
        "anchor.recipient_cif": "Recipient NIF/CIF (NIF/CIF del receptor/comprador)",
        "anchor.recipient_name": "Recipient company name (nombre del receptor)",
        "anchor.issue_date": "Invoice date in ISO YYYY-MM-DD format",
        "anchor.base_imponible": "Tax base / base imponible (number, no currency symbol)",
        "anchor.iva_rate": "IVA rate as percentage number (21 for 21%)",
        "anchor.iva_amount": "IVA amount in currency units (cuota IVA)",
        "anchor.irpf_rate": "IRPF retention rate as number (15 for 15%), null if absent",
        "anchor.irpf_amount": "IRPF retention amount, null if absent",
        "anchor.total_amount": "Total amount payable (total a pagar)",
        "anchor.currency": "Currency code (default EUR)",
    }

    async def extract_field(
        self,
        field_path: str,
        text: str,
        current_value: str | None = None,
    ) -> tuple[str | None, str]:
        """
        Re-extract a single field from document text.
        Returns (proposed_value, confidence) where confidence is:
        - "high": non-null + AnchorValidator finds no issues for this field
        - "medium": non-null + AnchorValidator flags an issue for this field
        - "low": null/empty result from LLM
        - "failed": exception during extraction
        """
        field_description = self._FIELD_DESCRIPTIONS.get(field_path, field_path)

        prompt = (
            f"Extract the following field from this invoice text:\n"
            f"Field: {field_description}\n"
            f"Current value: {current_value or 'unknown'}\n\n"
            f"Document text:\n{text[:3000]}\n\n"
            f"Respond with ONLY the extracted value, or 'null' if not found."
        )

        try:
            raw_response = await self._llm.complete(prompt)
            proposed = raw_response.strip()
            if proposed.lower() in ("null", "none", ""):
                return None, "low"

            # Validate using AnchorValidator — build a minimal AnchorFields with only
            # the field in question populated so the validator can run its checks.
            field_name = field_path.split(".")[-1] if "." in field_path else field_path
            # Use safe construction: only set the field if it's a valid AnchorFields attr
            import dataclasses as _dc
            anchor_field_names = {f.name for f in _dc.fields(AnchorFields)}
            if field_name in anchor_field_names:
                kwargs: dict = {field_name: proposed}
                test_anchor = AnchorFields(**kwargs)
            else:
                test_anchor = AnchorFields()

            issues = AnchorValidator().validate(test_anchor)
            field_issues = [i for i in issues if i.field == field_name]

            if not field_issues:
                return proposed, "high"
            else:
                return proposed, "medium"
        except Exception:
            return None, "failed"

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
            return str(v).strip() or None if v is not None else None

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
