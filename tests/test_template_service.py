from __future__ import annotations

import json
from decimal import Decimal

import pytest

from backend.schemas.extraction import AnchorFields, ExtractionIssue, ExtractionResult
from backend.services.template_service import (
    filter_extraction_by_template,
    parse_template_fields,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    anchor_kwargs: dict | None = None,
    discovered: dict | None = None,
) -> ExtractionResult:
    """Build a minimal ExtractionResult for testing."""
    anchor = AnchorFields(
        issuer_name="Test Issuer S.L.",
        issuer_cif="A12345679",
        recipient_name="Test Recipient S.A.",
        recipient_cif="12345678Z",
        invoice_number="INV-001",
        issue_date="2026-03-01",
        base_imponible=Decimal("100.00"),
        iva_rate=Decimal("21"),
        iva_amount=Decimal("21.00"),
        irpf_rate=None,
        irpf_amount=None,
        total_amount=Decimal("121.00"),
        currency="EUR",
        **(anchor_kwargs or {}),
    )
    return ExtractionResult(
        anchor=anchor,
        discovered=discovered or {},
        issues=[],
        requires_review=False,
        llm_model="test-model",
        extraction_timestamp="2026-03-01T00:00:00",
    )


# ---------------------------------------------------------------------------
# test_parse_template_fields
# ---------------------------------------------------------------------------


def test_parse_template_fields():
    fields_json = json.dumps(
        [
            {"field_path": "anchor.invoice_number", "display_name": "Invoice #", "include": True},
            {"field_path": "anchor.total_amount", "display_name": "Total", "include": False},
        ]
    )
    result = parse_template_fields(fields_json)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["field_path"] == "anchor.invoice_number"
    assert result[0]["display_name"] == "Invoice #"
    assert result[0]["include"] is True
    assert result[1]["field_path"] == "anchor.total_amount"
    assert result[1]["include"] is False


# ---------------------------------------------------------------------------
# test_filter_extraction_by_template_include_true
# ---------------------------------------------------------------------------


def test_filter_extraction_by_template_include_true():
    result = _make_result()
    template_fields = [
        {"field_path": "anchor.invoice_number", "display_name": "Invoice #", "include": True},
        {"field_path": "anchor.issuer_name", "display_name": "Issuer", "include": True},
    ]
    output = filter_extraction_by_template(result, template_fields)
    assert "Invoice #" in output
    assert output["Invoice #"] == "INV-001"
    assert "Issuer" in output
    assert output["Issuer"] == "Test Issuer S.L."


# ---------------------------------------------------------------------------
# test_filter_extraction_by_template_include_false
# ---------------------------------------------------------------------------


def test_filter_extraction_by_template_include_false():
    result = _make_result()
    template_fields = [
        {"field_path": "anchor.invoice_number", "display_name": "Invoice #", "include": True},
        {"field_path": "anchor.total_amount", "display_name": "Total", "include": False},
    ]
    output = filter_extraction_by_template(result, template_fields)
    assert "Invoice #" in output
    assert "Total" not in output


# ---------------------------------------------------------------------------
# test_filter_extraction_by_template_lines
# ---------------------------------------------------------------------------


def test_filter_extraction_by_template_lines():
    line_items = [{"concept": "Service A", "total": "100.00"}]
    result = _make_result(discovered={"line_items": line_items, "raw_text": "some text"})
    template_fields = [
        {"field_path": "lines", "display_name": "Line Items", "include": True},
    ]
    output = filter_extraction_by_template(result, template_fields)
    assert "Line Items" in output
    assert output["Line Items"] == line_items


# ---------------------------------------------------------------------------
# test_filter_extraction_by_template_empty
# ---------------------------------------------------------------------------


def test_filter_extraction_by_template_empty():
    result = _make_result()
    # completely empty list
    assert filter_extraction_by_template(result, []) == {}
    # all include=False
    template_fields = [
        {"field_path": "anchor.invoice_number", "display_name": "Invoice #", "include": False},
    ]
    assert filter_extraction_by_template(result, template_fields) == {}


# ---------------------------------------------------------------------------
# test_filter_extraction_discovered_field
# ---------------------------------------------------------------------------


def test_filter_extraction_discovered_field():
    result = _make_result(discovered={"raw_text": "Full OCR text here", "line_items": []})
    template_fields = [
        {"field_path": "discovered.raw_text", "display_name": "Raw Text", "include": True},
    ]
    output = filter_extraction_by_template(result, template_fields)
    assert "Raw Text" in output
    assert output["Raw Text"] == "Full OCR text here"


# ---------------------------------------------------------------------------
# test_parse_template_fields_invalid_json
# ---------------------------------------------------------------------------


def test_parse_template_fields_invalid_json():
    with pytest.raises(ValueError, match="fields_json is not valid JSON"):
        parse_template_fields("not valid json {{{")


# ---------------------------------------------------------------------------
# test_parse_template_fields_not_a_list
# ---------------------------------------------------------------------------


def test_parse_template_fields_not_a_list():
    with pytest.raises(ValueError, match="fields_json must be a JSON array"):
        parse_template_fields(json.dumps({"field_path": "anchor.total_amount"}))


# ---------------------------------------------------------------------------
# test_filter_extraction_unknown_prefix
# ---------------------------------------------------------------------------


def test_filter_extraction_unknown_prefix():
    result = _make_result()
    template_fields = [
        {"field_path": "foo.bar", "display_name": "Unknown Field", "include": True},
    ]
    output = filter_extraction_by_template(result, template_fields)
    assert "Unknown Field" in output
    assert output["Unknown Field"] is None
