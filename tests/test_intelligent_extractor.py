from __future__ import annotations
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from backend.schemas.extraction import ExtractionResult
from backend.services.intelligent_extractor import IntelligentExtractor, MAX_TEXT_CHARS
from backend.services.llm_service import LLMConnectionError, LLMParseError


_SAMPLE_RESPONSE = {
    "anchor": {
        "issuer_name": "INMOBILIARIA BARUAL S.L.",
        "issuer_cif": "A12345679",           # known-valid NIF for test
        "recipient_name": "GESTINAD ARAGON S.L.",
        "recipient_cif": "12345678Z",         # known-valid NIF for test
        "invoice_number": "GAT143/26",
        "issue_date": "2026-03-01",
        "base_imponible": "102.57",
        "iva_rate": "21",
        "iva_amount": "21.54",
        "irpf_rate": None,
        "irpf_amount": None,
        "total_amount": "124.11",
        "currency": "EUR",
    },
    "discovered": {"line_items": [{"concept": "RENTA LEGAL", "total": "102.57"}]},
    "llm_observations": ["IVA calculation looks correct"],
}


def _make_extractor(response=_SAMPLE_RESPONSE, side_effect=None) -> IntelligentExtractor:
    llm = MagicMock()
    if side_effect:
        llm.complete_json = AsyncMock(side_effect=side_effect)
    else:
        llm.complete_json = AsyncMock(return_value=response)
    return IntelligentExtractor(llm=llm)


@pytest.mark.asyncio
async def test_happy_path_populates_anchor():
    extractor = _make_extractor()
    result = await extractor.extract("Some OCR text", "invoice.pdf")
    assert isinstance(result, ExtractionResult)
    assert result.anchor.issuer_name == "INMOBILIARIA BARUAL S.L."
    assert result.anchor.total_amount == Decimal("124.11")
    assert result.anchor.currency == "EUR"


@pytest.mark.asyncio
async def test_happy_path_discovered_and_observations():
    extractor = _make_extractor()
    result = await extractor.extract("Some OCR text", "invoice.pdf")
    assert result.discovered == {"line_items": [{"concept": "RENTA LEGAL", "total": "102.57"}]}
    obs_messages = [i.message for i in result.issues if i.source == "llm"]
    assert "IVA calculation looks correct" in obs_messages


@pytest.mark.asyncio
async def test_missing_anchor_key_returns_null_anchor():
    extractor = _make_extractor(response={"something_else": {}})
    result = await extractor.extract("text", "invoice.pdf")
    assert result.anchor.issuer_name is None
    assert result.requires_review is True
    assert any("unexpected structure" in i.message.lower() for i in result.issues)


@pytest.mark.asyncio
async def test_empty_anchor_returns_null_anchor():
    extractor = _make_extractor(response={"anchor": {}, "discovered": {}, "llm_observations": []})
    result = await extractor.extract("text", "invoice.pdf")
    assert result.anchor.issuer_name is None
    assert result.requires_review is True


@pytest.mark.asyncio
async def test_llm_parse_error_returns_failure_result():
    extractor = _make_extractor(side_effect=LLMParseError("failed"))
    result = await extractor.extract("text", "invoice.pdf")
    assert result.anchor.issuer_name is None
    assert result.requires_review is True
    assert any("parse failure" in i.message.lower() for i in result.issues)


@pytest.mark.asyncio
async def test_llm_connection_error_propagates():
    extractor = _make_extractor(side_effect=LLMConnectionError("unreachable"))
    with pytest.raises(LLMConnectionError):
        await extractor.extract("text", "invoice.pdf")


@pytest.mark.asyncio
async def test_text_truncation_adds_warning():
    extractor = _make_extractor()
    long_text = "A" * (MAX_TEXT_CHARS + 1000)
    result = await extractor.extract(long_text, "invoice.pdf")
    assert any("truncated" in i.message.lower() for i in result.issues)


@pytest.mark.asyncio
async def test_text_within_limit_no_truncation_warning():
    extractor = _make_extractor()
    short_text = "A" * 100
    result = await extractor.extract(short_text, "invoice.pdf")
    assert not any("truncated" in i.message.lower() for i in result.issues)


@pytest.mark.asyncio
async def test_null_string_fields_become_none():
    resp = dict(_SAMPLE_RESPONSE)
    resp["anchor"] = {**_SAMPLE_RESPONSE["anchor"], "issuer_name": "", "invoice_number": None}
    extractor = _make_extractor(response=resp)
    result = await extractor.extract("text", "invoice.pdf")
    assert result.anchor.issuer_name is None
    assert result.anchor.invoice_number is None


# ── Phase 7: extract_field ──────────────────────────────────────────────────────

def _make_extractor_with_complete(return_value=None, side_effect=None) -> IntelligentExtractor:
    """Build an extractor where _llm.complete (not complete_json) is mocked."""
    llm = MagicMock()
    llm.complete_json = AsyncMock(return_value=_SAMPLE_RESPONSE)  # for extract() calls
    if side_effect:
        llm.complete = AsyncMock(side_effect=side_effect)
    else:
        llm.complete = AsyncMock(return_value=return_value)
    return IntelligentExtractor(llm=llm)


@pytest.mark.asyncio
async def test_extract_field_returns_high_confidence_when_valid():
    """When the LLM returns a plausible invoice number (no CIF validation needed),
    and AnchorValidator finds no issues, confidence should be 'high'."""
    # invoice_number is a free-form string — AnchorValidator never flags it,
    # so any non-empty response for anchor.invoice_number → high confidence.
    extractor = _make_extractor_with_complete(return_value="F-2026-001")
    proposed, confidence = await extractor.extract_field(
        "anchor.invoice_number", "Factura F-2026-001 emitida el 2026-01-15", current_value=None
    )
    assert proposed == "F-2026-001"
    assert confidence == "high"


@pytest.mark.asyncio
async def test_extract_field_returns_low_when_null_response():
    """When the LLM returns 'null', extract_field should return (None, 'low')."""
    extractor = _make_extractor_with_complete(return_value="null")
    proposed, confidence = await extractor.extract_field(
        "anchor.invoice_number", "Texto sin número de factura", current_value=None
    )
    assert proposed is None
    assert confidence == "low"


@pytest.mark.asyncio
async def test_extract_field_returns_failed_on_exception():
    """When the LLM raises an exception, extract_field should return (None, 'failed')."""
    extractor = _make_extractor_with_complete(side_effect=RuntimeError("model crashed"))
    proposed, confidence = await extractor.extract_field(
        "anchor.total_amount", "Invoice text", current_value="100.00"
    )
    assert proposed is None
    assert confidence == "failed"
