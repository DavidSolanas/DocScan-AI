# tests/test_table_merger.py
from __future__ import annotations

import pytest

from backend.services.table_extractor import (
    ExtractedTable,
    TableCell,
    merge_tables_across_pages,
)


# ---- Helper ----

def _make_table(
    page_num: int,
    nrows: int,
    ncols: int,
    method: str = "pdfplumber",
    first_row_numeric: bool = True,
) -> ExtractedTable:
    """Build an ExtractedTable with synthetic cell content."""
    cells: list[TableCell] = []
    for r in range(nrows):
        for c in range(ncols):
            if r == 0 and not first_row_numeric:
                text = f"Header{c}"
            else:
                text = f"{r * 10 + c + 1}.00"
            cells.append(TableCell(row=r, col=c, text=text))
    return ExtractedTable(
        cells=cells,
        num_rows=nrows,
        num_cols=ncols,
        extraction_method=method,
        page_number=page_num,
    )


# ---- Tests ----

def test_empty_input():
    assert merge_tables_across_pages({}) == []


def test_single_page_no_merge():
    t1 = _make_table(1, 3, 2)
    t2 = _make_table(1, 2, 3)
    result = merge_tables_across_pages({1: [t1, t2]})
    assert len(result) == 2


def test_two_pages_merge_when_cols_match_and_continuation():
    base = _make_table(1, 4, 3)
    cont = _make_table(2, 3, 3, first_row_numeric=True)
    result = merge_tables_across_pages({1: [base], 2: [cont]})
    assert len(result) == 1
    assert result[0].num_rows == 7  # 4 + 3


def test_no_merge_when_col_count_differs():
    base = _make_table(1, 3, 3)
    cont = _make_table(2, 2, 4)  # different col count
    result = merge_tables_across_pages({1: [base], 2: [cont]})
    assert len(result) == 2


def test_no_merge_when_page2_has_header_row():
    base = _make_table(1, 3, 3)
    cont = _make_table(2, 3, 3, first_row_numeric=False)  # all-string first row
    result = merge_tables_across_pages({1: [base], 2: [cont]})
    assert len(result) == 2


def test_row_indices_offset_correctly():
    base = _make_table(1, 4, 2)
    cont = _make_table(2, 3, 2, first_row_numeric=True)
    result = merge_tables_across_pages({1: [base], 2: [cont]})
    assert len(result) == 1
    merged = result[0]
    # The continuation's first row (row=0) should be offset to row=4
    cont_cells = [c for c in merged.cells if c.row >= 4]
    assert len(cont_cells) > 0
    row_values = {c.row for c in cont_cells}
    assert min(row_values) == 4


def test_three_page_merge():
    t1 = _make_table(1, 3, 2)
    t2 = _make_table(2, 3, 2, first_row_numeric=True)
    t3 = _make_table(3, 2, 2, first_row_numeric=True)
    result = merge_tables_across_pages({1: [t1], 2: [t2], 3: [t3]})
    assert len(result) == 1
    assert result[0].num_rows == 8  # 3 + 3 + 2


def test_extraction_method_includes_merged():
    base = _make_table(1, 3, 2, method="camelot")
    cont = _make_table(2, 2, 2, first_row_numeric=True)
    result = merge_tables_across_pages({1: [base], 2: [cont]})
    assert "merged" in result[0].extraction_method


def test_page_number_preserved_from_first_page():
    base = _make_table(1, 3, 2)
    cont = _make_table(2, 2, 2, first_row_numeric=True)
    result = merge_tables_across_pages({1: [base], 2: [cont]})
    assert result[0].page_number == 1
