"""IVA quarterly summary — aggregates across all indexed invoices."""
from __future__ import annotations

import json
import logging
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Extraction

logger = logging.getLogger(__name__)

_TWO = Decimal("0.01")


def _fmt(v: Decimal) -> str:
    return str(v.quantize(_TWO, rounding=ROUND_HALF_UP))


async def compute_iva_summary(
    db: AsyncSession,
    date_from: str | None,
    date_to: str | None,
    role: str = "recipient",
) -> dict:
    """
    Aggregate IVA data grouped by rate for a date range.

    Reads base_imponible, iva_rate, iva_amount, irpf_amount from JSON files
    (these are NOT stored in the DB, only in json_path).
    """
    stmt = select(Extraction)
    # Apply date filters (string comparison works for ISO dates)
    if date_from:
        stmt = stmt.where(Extraction.issue_date >= date_from)
    if date_to:
        stmt = stmt.where(Extraction.issue_date <= date_to)

    result = await db.execute(stmt)
    extractions = list(result.scalars().all())

    # Aggregation: rate -> {base_imponible, iva_amount, count}
    rate_groups: dict[str, dict] = {}
    total_irpf = Decimal("0")

    for ext in extractions:
        try:
            path = Path(ext.json_path)
            if not path.exists():
                logger.warning("JSON file not found for extraction %s: %s", ext.id, ext.json_path)
                continue
            raw = json.loads(path.read_text())
            anchor = raw.get("anchor") or {}

            base_str = anchor.get("base_imponible")
            iva_rate_str = anchor.get("iva_rate")
            iva_amount_str = anchor.get("iva_amount")
            irpf_str = anchor.get("irpf_amount")

            if base_str is None and iva_rate_str is None:
                continue  # no financial data in this invoice

            base = Decimal(str(base_str)) if base_str is not None else Decimal("0")
            iva_rate_val = Decimal(str(iva_rate_str)) if iva_rate_str is not None else Decimal("0")
            iva_amount_val = (
                Decimal(str(iva_amount_str)) if iva_amount_str is not None else Decimal("0")
            )
            irpf_val = Decimal(str(irpf_str)) if irpf_str is not None else Decimal("0")

            rate_key = _fmt(iva_rate_val)
            if rate_key not in rate_groups:
                rate_groups[rate_key] = {
                    "base_imponible_total": Decimal("0"),
                    "iva_total": Decimal("0"),
                    "invoice_count": 0,
                }
            rate_groups[rate_key]["base_imponible_total"] += base
            rate_groups[rate_key]["iva_total"] += iva_amount_val
            rate_groups[rate_key]["invoice_count"] += 1
            total_irpf += irpf_val

        except Exception as exc:
            logger.warning("Could not process extraction %s: %s", ext.id, exc)
            continue

    rates = [
        {
            "iva_rate": rate,
            "base_imponible_total": _fmt(data["base_imponible_total"]),
            "iva_total": _fmt(data["iva_total"]),
            "invoice_count": data["invoice_count"],
        }
        for rate, data in sorted(rate_groups.items())
    ]

    total_base = sum((d["base_imponible_total"] for d in rate_groups.values()), Decimal("0"))
    total_iva = sum((d["iva_total"] for d in rate_groups.values()), Decimal("0"))
    total_count = sum(d["invoice_count"] for d in rate_groups.values())

    return {
        "period": {"from": date_from, "to": date_to},
        "role": role,
        "rates": rates,
        "totals": {
            "base_imponible_total": _fmt(total_base),
            "iva_total": _fmt(total_iva),
            "irpf_total": _fmt(total_irpf),
            "invoice_count": total_count,
        },
    }
