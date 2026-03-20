from __future__ import annotations
from dataclasses import asdict
from decimal import Decimal
from backend.schemas.extraction import AnchorFields, ExtractionIssue, ExtractionResult


def _make_anchor(**kwargs) -> AnchorFields:
    defaults = dict(
        issuer_name=None, issuer_cif=None, recipient_name=None, recipient_cif=None,
        invoice_number=None, issue_date=None, base_imponible=None, iva_rate=None,
        iva_amount=None, irpf_rate=None, irpf_amount=None, total_amount=None, currency="EUR",
    )
    return AnchorFields(**{**defaults, **kwargs})


def test_anchor_asdict_preserves_decimal():
    anchor = _make_anchor(base_imponible=Decimal("102.57"), total_amount=Decimal("124.11"))
    d = asdict(anchor)
    assert d["base_imponible"] == Decimal("102.57")
    assert d["currency"] == "EUR"


def test_extraction_issue_asdict():
    issue = ExtractionIssue(field="issuer_cif", message="Invalid CIF", severity="error", source="validator")
    d = asdict(issue)
    assert d == {"field": "issuer_cif", "message": "Invalid CIF", "severity": "error", "source": "validator"}


def test_extraction_result_from_dict_round_trip():
    anchor = _make_anchor(
        issuer_name="Test SL", issuer_cif="B50042332",
        invoice_number="F-001", issue_date="2026-03-01",
        base_imponible=Decimal("102.57"), iva_rate=Decimal("21"),
        iva_amount=Decimal("21.54"), total_amount=Decimal("124.11"),
    )
    result = ExtractionResult(
        anchor=anchor, discovered={"line_items": []}, issues=[],
        requires_review=False, llm_model="qwen3.5:9b",
        extraction_timestamp="2026-03-20T10:00:00Z",
    )
    from decimal import Decimal as D
    import json, dataclasses
    def _default(obj):
        if isinstance(obj, D): return str(obj)
        raise TypeError
    raw = json.loads(json.dumps(dataclasses.asdict(result), default=_default))
    restored = ExtractionResult.from_dict(raw)
    assert restored.anchor.issuer_name == "Test SL"
    assert restored.anchor.base_imponible == Decimal("102.57")
    assert restored.anchor.currency == "EUR"
    assert restored.requires_review is False
