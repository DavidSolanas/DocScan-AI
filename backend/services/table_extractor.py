"""Table extraction from digital PDFs (pdfplumber/camelot) and scanned images (PP-Structure)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import numpy as np


@dataclass
class TableCell:
    row: int
    col: int
    text: str
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)  # (x1, y1, x2, y2)
    rowspan: int = 1
    colspan: int = 1


@dataclass
class ExtractedTable:
    cells: list[TableCell] = field(default_factory=list)
    num_rows: int = 0
    num_cols: int = 0
    extraction_method: str = "unknown"
    page_number: int = 1
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)

    def to_matrix(self) -> list[list[str]]:
        """Convert cells to a 2D list[row][col] of strings."""
        if not self.cells:
            return []
        matrix = [[""] * self.num_cols for _ in range(self.num_rows)]
        for cell in self.cells:
            if 0 <= cell.row < self.num_rows and 0 <= cell.col < self.num_cols:
                matrix[cell.row][cell.col] = cell.text
        return matrix


# ──────────────────────────────────────────────────────────────────────────────
# Digital PDF extraction
# ──────────────────────────────────────────────────────────────────────────────

def _extract_tables_pdfplumber(pdf_path: str, page_number: int) -> list[ExtractedTable]:
    """Extract tables from a digital PDF page using pdfplumber."""
    try:
        import pdfplumber  # type: ignore[import]  # noqa: PLC0415
    except ImportError:
        return []

    tables: list[ExtractedTable] = []
    with pdfplumber.open(pdf_path) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            return []
        page = pdf.pages[page_number - 1]
        for raw_table in page.extract_tables() or []:
            if not raw_table:
                continue
            num_rows = len(raw_table)
            num_cols = max((len(row) for row in raw_table), default=0)
            cells = [
                TableCell(row=r, col=c, text=(cell or "").strip())
                for r, row in enumerate(raw_table)
                for c, cell in enumerate(row)
            ]
            tables.append(
                ExtractedTable(
                    cells=cells,
                    num_rows=num_rows,
                    num_cols=num_cols,
                    extraction_method="pdfplumber",
                    page_number=page_number,
                )
            )
    return tables


def _extract_tables_camelot(pdf_path: str, page_number: int) -> list[ExtractedTable]:
    """Extract tables from a digital PDF page using camelot-py."""
    try:
        import camelot  # type: ignore[import]  # noqa: PLC0415
    except ImportError:
        return []

    for flavor in ("lattice", "stream"):
        try:
            raw_tables = camelot.read_pdf(pdf_path, pages=str(page_number), flavor=flavor)
            break
        except Exception:
            raw_tables = None
    else:
        return []

    if raw_tables is None:
        return []

    tables: list[ExtractedTable] = []
    for table in raw_tables:
        df = table.df
        num_rows, num_cols = df.shape
        cells = [
            TableCell(row=r, col=c, text=str(df.iloc[r, c]).strip())
            for r in range(num_rows)
            for c in range(num_cols)
        ]
        tables.append(
            ExtractedTable(
                cells=cells,
                num_rows=num_rows,
                num_cols=num_cols,
                extraction_method="camelot",
                page_number=page_number,
            )
        )
    return tables


# ──────────────────────────────────────────────────────────────────────────────
# Scanned image extraction via PP-Structure
# ──────────────────────────────────────────────────────────────────────────────

def _parse_html_table(html: str) -> ExtractedTable | None:
    """Parse an HTML <table> string into an ExtractedTable."""
    try:
        root = ElementTree.fromstring(f"<root>{html}</root>")
    except ElementTree.ParseError:
        return None

    table_el = root.find(".//table")
    if table_el is None:
        return None

    cells: list[TableCell] = []
    for r_idx, row in enumerate(table_el.findall(".//tr")):
        col_cursor = 0
        for td in list(row.findall("td")) + list(row.findall("th")):
            text = "".join(td.itertext()).strip()
            colspan = int(td.get("colspan", 1))
            rowspan = int(td.get("rowspan", 1))
            cells.append(
                TableCell(
                    row=r_idx,
                    col=col_cursor,
                    text=text,
                    colspan=colspan,
                    rowspan=rowspan,
                )
            )
            col_cursor += colspan

    if not cells:
        return None

    num_rows = max(c.row for c in cells) + 1
    num_cols = max(c.col + c.colspan - 1 for c in cells) + 1
    return ExtractedTable(cells=cells, num_rows=num_rows, num_cols=num_cols)


def _extract_tables_ppstructure(
    image: np.ndarray, page_number: int = 1
) -> list[ExtractedTable]:
    """Extract tables from a scanned image using PaddleOCR PP-Structure."""
    try:
        from paddleocr import PPStructure  # type: ignore[import]  # noqa: PLC0415
    except ImportError:
        return []

    try:
        engine = PPStructure(table=True, ocr=True, show_log=False)
        result = engine(image)

        tables: list[ExtractedTable] = []
        for region in result or []:
            if region.get("type") != "table":
                continue
            html = region.get("res", {}).get("html", "")
            if not html:
                continue
            parsed = _parse_html_table(html)
            if parsed is None:
                continue
            parsed.page_number = page_number
            parsed.extraction_method = "ppstructure"
            raw_bbox = region.get("bbox", [0, 0, 0, 0])
            parsed.bbox = tuple(int(v) for v in raw_bbox[:4])  # type: ignore[assignment]
            tables.append(parsed)

        return tables
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def extract_tables_from_pdf(
    pdf_path: str | Path, page_number: int = 1
) -> list[ExtractedTable]:
    """Extract tables from a digital PDF page (synchronous).

    Tries camelot first (better for ruled tables), falls back to pdfplumber.
    """
    tables = _extract_tables_camelot(str(pdf_path), page_number)
    if not tables:
        tables = _extract_tables_pdfplumber(str(pdf_path), page_number)
    return tables


def extract_tables_from_image(
    image: np.ndarray, page_number: int = 1
) -> list[ExtractedTable]:
    """Extract tables from a scanned image using PP-Structure (synchronous)."""
    return _extract_tables_ppstructure(image, page_number)


async def extract_tables_from_pdf_async(
    pdf_path: str | Path, page_number: int = 1
) -> list[ExtractedTable]:
    """Async wrapper for PDF table extraction."""
    return await asyncio.to_thread(extract_tables_from_pdf, pdf_path, page_number)


async def extract_tables_from_image_async(
    image: np.ndarray, page_number: int = 1
) -> list[ExtractedTable]:
    """Async wrapper for image table extraction."""
    return await asyncio.to_thread(extract_tables_from_image, image, page_number)


def _is_numeric_cell(text: str) -> bool:
    """Return True if the cell text looks like a number or price."""
    t = text.strip()
    if not t:
        return False
    try:
        float(t.replace(",", "."))
        return True
    except ValueError:
        pass
    # Price pattern: digits with optional thousands/decimal separators
    import re
    return bool(re.match(r"^[\d][\d.,\s]*$", t))


def merge_tables_across_pages(
    tables_by_page: dict[int, list[ExtractedTable]],
) -> list[ExtractedTable]:
    """Merge tables that span multiple pages.

    Algorithm:
    1. For each page N, check if the last table on page N can be merged with the
       first table on page N+1 (column count must match, continuation heuristic).
    2. Continuation heuristic: page N+1 first table has ≥2 rows AND its first row
       contains at least one numeric-looking cell. If the first row is ALL non-numeric
       strings, treat it as a new header row and do NOT merge.
    3. Repeat until stable to handle 3+ page tables.
    4. Return a flat list of all tables (merged multi-page + standalone), preserving
       page_number from the first contributing page.
    """
    if not tables_by_page:
        return []

    # Work on mutable copies of each page's list
    pages_work: dict[int, list[ExtractedTable]] = {
        p: list(tbls) for p, tbls in tables_by_page.items()
    }
    sorted_pages = sorted(pages_work.keys())

    changed = True
    while changed:
        changed = False
        for idx, page_n in enumerate(sorted_pages[:-1]):
            base_list = pages_work[page_n]
            if not base_list:
                continue

            # Find the next non-empty page after page_n
            next_page = None
            for p in sorted_pages[idx + 1:]:
                if pages_work[p]:
                    next_page = p
                    break
            if next_page is None:
                continue

            cont_list = pages_work[next_page]
            base = base_list[-1]
            cont = cont_list[0]

            # Column count must match
            if base.num_cols != cont.num_cols or cont.num_rows < 2:
                continue

            # Continuation heuristic: first row must have at least one numeric cell
            first_row_cells = [c for c in cont.cells if c.row == 0]
            if not first_row_cells:
                continue
            if not any(_is_numeric_cell(c.text) for c in first_row_cells):
                continue  # All-string first row → new header, do not merge

            # Merge: offset continuation cells by base.num_rows
            offset = base.num_rows
            for cell in cont.cells:
                cell.row += offset
            base.cells.extend(cont.cells)
            base.num_rows += cont.num_rows
            base.extraction_method = base.extraction_method + "+merged"

            cont_list.pop(0)
            changed = True

    # Flatten all pages' tables into a single list
    result: list[ExtractedTable] = []
    for page_n in sorted_pages:
        result.extend(pages_work[page_n])
    return result


async def merge_tables_across_pages_async(
    tables_by_page: dict[int, list[ExtractedTable]],
) -> list[ExtractedTable]:
    """Async wrapper for merge_tables_across_pages."""
    return await asyncio.to_thread(merge_tables_across_pages, tables_by_page)
