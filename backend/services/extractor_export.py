from __future__ import annotations
import csv, io
from backend.schemas.extraction import ExtractionResult


def to_markdown(result: ExtractionResult, filename: str) -> str:
    a = result.anchor
    lines: list[str] = []

    inv_num = a.invoice_number or "—"
    issuer = a.issuer_name or "—"
    lines.append(f"# Factura {inv_num} — {issuer}")
    lines.append("")

    meta = []
    if a.issue_date:
        meta.append(f"**Fecha:** {a.issue_date}")
    if a.issuer_cif:
        meta.append(f"**Emisor CIF:** {a.issuer_cif}")
    if a.recipient_cif:
        meta.append(f"**Receptor CIF:** {a.recipient_cif}")
    if meta:
        lines.append("  |  ".join(meta))
        lines.append("")

    lines += ["## Resumen Fiscal", "", "| Campo | Valor |", "|---|---|"]
    if a.base_imponible is not None:
        lines.append(f"| Base imponible | {a.base_imponible} {a.currency} |")
    if a.iva_rate is not None and a.iva_amount is not None:
        lines.append(f"| IVA ({a.iva_rate}%) | {a.iva_amount} {a.currency} |")
    if a.irpf_rate is not None and a.irpf_amount is not None:
        lines.append(f"| IRPF ({a.irpf_rate}%) | -{a.irpf_amount} {a.currency} |")
    if a.total_amount is not None:
        lines.append(f"| **Total** | **{a.total_amount} {a.currency}** |")
    lines.append("")

    lines += ["## Partes", ""]
    if a.issuer_name or a.issuer_cif:
        lines.append(f"**Emisor:** {a.issuer_name or '—'} ({a.issuer_cif or '—'})")
    if a.recipient_name or a.recipient_cif:
        lines.append(f"**Receptor:** {a.recipient_name or '—'} ({a.recipient_cif or '—'})")
    lines.append("")

    if result.discovered:
        lines += ["## Detalles Adicionales", ""]
        _render_dict(result.discovered, lines, indent=0)
        lines.append("")

    if result.issues:
        lines += ["## Observaciones e Incidencias", ""]
        icons = {"error": "❌", "warning": "⚠️", "observation": "ℹ️"}
        for issue in result.issues:
            icon = icons.get(issue.severity, "•")
            field_note = f" (`{issue.field}`)" if issue.field else ""
            lines.append(f"- {icon}{field_note} {issue.message}")
        lines.append("")

    lines.append(f"*Extraído con {result.llm_model} el {result.extraction_timestamp}*")
    return "\n".join(lines)


def _render_dict(d: dict, lines: list[str], indent: int) -> None:
    prefix = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{prefix}- **{k}:**")
            _render_dict(v, lines, indent + 1)
        else:
            lines.append(f"{prefix}- **{k}:** {v}")


def to_csv(result: ExtractionResult) -> str:
    a = result.anchor
    fieldnames = [
        "invoice_number", "issue_date", "issuer_name", "issuer_cif",
        "recipient_name", "recipient_cif", "base_imponible", "iva_rate",
        "iva_amount", "irpf_rate", "irpf_amount", "total_amount", "currency",
        "issues_count", "requires_review",
    ]

    def _s(v: object) -> str:
        return "" if v is None else str(v)

    row = {
        "invoice_number": _s(a.invoice_number), "issue_date": _s(a.issue_date),
        "issuer_name": _s(a.issuer_name), "issuer_cif": _s(a.issuer_cif),
        "recipient_name": _s(a.recipient_name), "recipient_cif": _s(a.recipient_cif),
        "base_imponible": _s(a.base_imponible), "iva_rate": _s(a.iva_rate),
        "iva_amount": _s(a.iva_amount), "irpf_rate": _s(a.irpf_rate),
        "irpf_amount": _s(a.irpf_amount), "total_amount": _s(a.total_amount),
        "currency": a.currency,
        "issues_count": str(sum(1 for i in result.issues if i.severity == "error")),
        "requires_review": str(result.requires_review).lower(),
    }
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerow(row)
    return out.getvalue()
