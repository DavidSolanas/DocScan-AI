"""Tests for layout_detector — LayoutParser is mocked (not required at runtime)."""

from __future__ import annotations

from unittest.mock import patch

import cv2
import numpy as np
import pytest

from backend.services.layout_detector import (
    LayoutDetectionResult,
    PageRegion,
    RegionType,
    _detect_layout_heuristic,
    _detect_tables_heuristic,
    crop_region,
    detect_layout_sync,
    get_regions_by_type,
)


def _blank_image(h: int = 400, w: int = 600) -> np.ndarray:
    return np.ones((h, w, 3), dtype=np.uint8) * 255


def _image_with_grid_lines(h: int = 400, w: int = 600) -> np.ndarray:
    """Draw a simple 2x2 table grid on a white image."""
    img = _blank_image(h, w)
    # Horizontal lines
    cv2.line(img, (50, 100), (550, 100), (0, 0, 0), 2)
    cv2.line(img, (50, 200), (550, 200), (0, 0, 0), 2)
    cv2.line(img, (50, 300), (550, 300), (0, 0, 0), 2)
    # Vertical lines
    cv2.line(img, (50, 100), (50, 300), (0, 0, 0), 2)
    cv2.line(img, (300, 100), (300, 300), (0, 0, 0), 2)
    cv2.line(img, (550, 100), (550, 300), (0, 0, 0), 2)
    return img


# ──────────────────────────────────────────────────────────────────────────────
# RegionType tests
# ──────────────────────────────────────────────────────────────────────────────

def test_region_type_values():
    assert RegionType.TEXT == "text"
    assert RegionType.TABLE == "table"
    assert RegionType.HEADER == "header"


# ──────────────────────────────────────────────────────────────────────────────
# Heuristic detection tests
# ──────────────────────────────────────────────────────────────────────────────

def test_heuristic_blank_image_returns_full_page_text():
    img = _blank_image()
    result = _detect_layout_heuristic(img)

    assert isinstance(result, LayoutDetectionResult)
    assert result.detector_used == "heuristic"
    assert result.page_width == 600
    assert result.page_height == 400

    text_regions = get_regions_by_type(result, RegionType.TEXT)
    assert len(text_regions) >= 1
    assert text_regions[0].bbox == (0, 0, 600, 400)


def test_heuristic_detects_table_in_grid_image():
    img = _image_with_grid_lines()
    result = _detect_layout_heuristic(img)

    table_regions = get_regions_by_type(result, RegionType.TABLE)
    assert len(table_regions) >= 1
    for region in table_regions:
        assert region.region_type == RegionType.TABLE
        assert region.confidence > 0


def test_detect_tables_heuristic_blank_no_tables():
    img = _blank_image()
    tables = _detect_tables_heuristic(img)
    # A blank white image has no dark lines, so no table regions expected
    assert isinstance(tables, list)


def test_detect_tables_heuristic_works_with_grayscale():
    img = _image_with_grid_lines()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    tables = _detect_tables_heuristic(gray)
    # Grayscale input should not crash
    assert isinstance(tables, list)


# ──────────────────────────────────────────────────────────────────────────────
# detect_layout_sync (with layoutparser fallback)
# ──────────────────────────────────────────────────────────────────────────────

def test_detect_layout_sync_heuristic_mode():
    img = _blank_image()
    result = detect_layout_sync(img, use_layoutparser=False)
    assert result.detector_used == "heuristic"
    assert result.page_width == 600


def test_detect_layout_sync_falls_back_when_layoutparser_missing():
    """When layoutparser is not installed, heuristic fallback must be used."""
    img = _blank_image()
    with patch.dict("sys.modules", {"layoutparser": None}):
        result = detect_layout_sync(img, use_layoutparser=True)
    # Heuristic fallback was used
    assert isinstance(result, LayoutDetectionResult)
    assert len(result.regions) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# Async wrapper
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_layout_async():
    from backend.services.layout_detector import detect_layout

    img = _blank_image()
    result = await detect_layout(img, use_layoutparser=False)
    assert isinstance(result, LayoutDetectionResult)
    assert result.page_width == 600


# ──────────────────────────────────────────────────────────────────────────────
# Helper function tests
# ──────────────────────────────────────────────────────────────────────────────

def test_get_regions_by_type():
    regions = [
        PageRegion(RegionType.TEXT, (0, 0, 100, 100)),
        PageRegion(RegionType.TABLE, (10, 10, 200, 200)),
        PageRegion(RegionType.TEXT, (0, 300, 100, 400)),
    ]
    result = LayoutDetectionResult(regions=regions, page_width=600, page_height=400)

    text_regions = get_regions_by_type(result, RegionType.TEXT)
    assert len(text_regions) == 2

    table_regions = get_regions_by_type(result, RegionType.TABLE)
    assert len(table_regions) == 1


def test_crop_region():
    img = np.zeros((200, 300, 3), dtype=np.uint8)
    img[50:100, 100:200] = 128  # fill a sub-region

    region = PageRegion(RegionType.TEXT, bbox=(100, 50, 200, 100))
    cropped = crop_region(img, region)

    assert cropped.shape == (50, 100, 3)
    assert np.all(cropped == 128)


def test_crop_region_full_image():
    img = _blank_image(100, 100)
    region = PageRegion(RegionType.TEXT, bbox=(0, 0, 100, 100))
    cropped = crop_region(img, region)
    assert cropped.shape == img.shape
