"""Export API — IVA summary endpoints."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import AsyncSessionLocal, get_db  # noqa: F401
from backend.services.iva_summary import compute_iva_summary

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/iva-summary")
async def get_iva_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    role: str = "recipient",
    db: AsyncSession = Depends(get_db),
):
    """Return IVA quarterly summary as JSON."""
    return await compute_iva_summary(db, date_from=date_from, date_to=date_to, role=role)


@router.get("/iva-summary/csv")
async def get_iva_summary_csv(
    date_from: str | None = None,
    date_to: str | None = None,
    role: str = "recipient",
    db: AsyncSession = Depends(get_db),
):
    """Return IVA quarterly summary as CSV download."""
    summary = await compute_iva_summary(db, date_from=date_from, date_to=date_to, role=role)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["IVA Rate", "Base Imponible Total", "IVA Total", "Invoice Count"])
    for rate_row in summary["rates"]:
        writer.writerow([
            f"{rate_row['iva_rate']}%",
            rate_row["base_imponible_total"],
            rate_row["iva_total"],
            rate_row["invoice_count"],
        ])
    totals = summary["totals"]
    writer.writerow([
        "TOTAL",
        totals["base_imponible_total"],
        totals["iva_total"],
        totals["invoice_count"],
    ])

    content = buf.getvalue().encode("utf-8")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="iva-summary.csv"'},
    )
