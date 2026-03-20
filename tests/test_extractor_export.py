from __future__ import annotations
import csv, io
from decimal import Decimal
from backend.schemas.extraction import AnchorFields, ExtractionIssue, ExtractionResult
from backend.services.extractor_export import to_csv, to_markdown


def _make_result(issues=None) -> ExtractionResult:
    anchor = AnchorFields(
        issuer_name="INMOBILIARIA BARUAL S.L.", issuer_cif="B50042332",
        recipient_name="GESTINAD ARAGON S.L.", recipient_cif="B99334708",
        invoice_number="GAT143/26", issue_date="2026-03-01",
        base_imponible=Decimal("102.57"), iva_rate=Decimal("21"),
        iva_amount=Decimal("21.54"), irpf_rate=None, irpf_amount=None,
        total_amount=Decimal("124.11"), currency="EUR",
    )
    return ExtractionResult(
        anchor=anchor,
        discovered={"line_items": [{"concept": "RENTA LEGAL", "total": "102.57"}]},
        issues=issues or [
            ExtractionIssue(field=None, message="IVA looks correct", severity="observation", source="llm")
        ],
        requires_review=False, llm_model="qwen3.5:9b",
        extraction_timestamp="2026-03-01T10:00:00Z",
    )


def test_markdown_contains_invoice_number():
    md = to_markdown(_make_result(), "invoice.pdf")
    assert "GAT143/26" in md


def test_markdown_contains_fiscal_values():
    md = to_markdown(_make_result(), "invoice.pdf")
    assert "102.57" in md
    assert "21.54" in md
    assert "124.11" in md


def test_markdown_contains_issuer_and_recipient():
    md = to_markdown(_make_result(), "invoice.pdf")
    assert "INMOBILIARIA BARUAL" in md
    assert "GESTINAD ARAGON" in md


def test_markdown_contains_discovered_section():
    md = to_markdown(_make_result(), "invoice.pdf")
    assert "RENTA LEGAL" in md


def test_markdown_contains_observations():
    md = to_markdown(_make_result(), "invoice.pdf")
    assert "IVA looks correct" in md


def test_markdown_with_irpf():
    from copy import deepcopy
    result = _make_result()
    result.anchor.irpf_rate = Decimal("15")
    result.anchor.irpf_amount = Decimal("15.39")
    md = to_markdown(result, "invoice.pdf")
    assert "15" in md
    assert "15.39" in md


def test_csv_has_correct_headers():
    out = to_csv(_make_result())
    reader = csv.DictReader(io.StringIO(out))
    assert "invoice_number" in reader.fieldnames
    assert "issuer_cif" in reader.fieldnames
    assert "total_amount" in reader.fieldnames
    assert "requires_review" in reader.fieldnames


def test_csv_has_correct_values():
    out = to_csv(_make_result())
    rows = list(csv.DictReader(io.StringIO(out)))
    assert len(rows) == 1
    row = rows[0]
    assert row["invoice_number"] == "GAT143/26"
    assert row["issuer_cif"] == "B50042332"
    assert row["total_amount"] == "124.11"
    assert row["requires_review"] == "false"


def test_csv_none_fields_are_empty_string():
    result = _make_result()
    result.anchor.irpf_rate = None
    out = to_csv(result)
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows[0]["irpf_rate"] == ""


def test_csv_empty_discovered_no_crash():
    result = _make_result()
    result.discovered = {}
    out = to_csv(result)
    assert "invoice_number" in out
