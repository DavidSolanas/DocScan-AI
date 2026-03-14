"""Layout detection: LayoutParser (when available) with heuristic fallback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum

import cv2
import numpy as np


class RegionType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    HEADER = "header"
    FOOTER = "footer"
    FIGURE = "figure"
    LIST = "list"
    STAMP = "stamp"
    UNKNOWN = "unknown"


@dataclass
class PageRegion:
    region_type: RegionType
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float = 1.0
    label: str = ""


@dataclass
class LayoutDetectionResult:
    regions: list[PageRegion] = field(default_factory=list)
    page_width: int = 0
    page_height: int = 0
    detector_used: str = "heuristic"


# ──────────────────────────────────────────────────────────────────────────────
# Heuristic detection (no extra dependencies)
# ──────────────────────────────────────────────────────────────────────────────

def _detect_tables_heuristic(image: np.ndarray) -> list[PageRegion]:
    """Detect table regions by finding horizontal+vertical line intersections."""
    h, w = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Horizontal lines
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 30), 1))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_h)

    # Vertical lines
    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 30)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_v)

    table_mask = cv2.add(horizontal, vertical)
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
    table_mask = cv2.dilate(table_mask, dilate_kernel)

    contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions: list[PageRegion] = []
    min_table_area = h * w * 0.01  # at least 1% of page
    pad = 10
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw * ch >= min_table_area:
            regions.append(
                PageRegion(
                    region_type=RegionType.TABLE,
                    bbox=(
                        max(0, x - pad),
                        max(0, y - pad),
                        min(w, x + cw + pad),
                        min(h, y + ch + pad),
                    ),
                    confidence=0.8,
                )
            )
    return regions


def _detect_layout_heuristic(image: np.ndarray) -> LayoutDetectionResult:
    """Heuristic layout: detect table regions, treat remainder as full-page text."""
    h, w = image.shape[:2]
    table_regions = _detect_tables_heuristic(image)
    all_regions = table_regions + [
        PageRegion(
            region_type=RegionType.TEXT,
            bbox=(0, 0, w, h),
            confidence=1.0,
            label="full_page",
        )
    ]
    return LayoutDetectionResult(
        regions=all_regions,
        page_width=w,
        page_height=h,
        detector_used="heuristic",
    )


# ──────────────────────────────────────────────────────────────────────────────
# LayoutParser detection (optional dependency)
# ──────────────────────────────────────────────────────────────────────────────

_LP_LABEL_MAP: dict[str, RegionType] = {
    "Text": RegionType.TEXT,
    "Title": RegionType.HEADER,
    "List": RegionType.LIST,
    "Table": RegionType.TABLE,
    "Figure": RegionType.FIGURE,
}


def _detect_layout_layoutparser(image: np.ndarray) -> LayoutDetectionResult:
    """LayoutParser + Detectron2 detection. Falls back to heuristic on failure."""
    try:
        import layoutparser as lp  # type: ignore[import]  # noqa: PLC0415

        model = lp.Detectron2LayoutModel(
            "lp://PubLayNet/faster_rcnn_R_50_FPN_3x/config",
            extra_config=["MODEL.ROI_HEADS.SCORE_THRESH_TEST", 0.5],
            label_map={0: "Text", 1: "Title", 2: "List", 3: "Table", 4: "Figure"},
        )

        if len(image.shape) == 2:
            rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        elif image.shape[2] == 4:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        layout = model.detect(rgb)
        h, w = image.shape[:2]

        regions: list[PageRegion] = []
        for block in layout:
            region_type = _LP_LABEL_MAP.get(block.type, RegionType.UNKNOWN)
            coords = block.block.coordinates  # (x1, y1, x2, y2)
            regions.append(
                PageRegion(
                    region_type=region_type,
                    bbox=(
                        int(coords[0]),
                        int(coords[1]),
                        int(coords[2]),
                        int(coords[3]),
                    ),
                    confidence=float(block.score),
                    label=block.type,
                )
            )

        return LayoutDetectionResult(
            regions=regions,
            page_width=w,
            page_height=h,
            detector_used="layoutparser",
        )
    except Exception:
        return _detect_layout_heuristic(image)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def detect_layout_sync(
    image: np.ndarray,
    use_layoutparser: bool = True,
) -> LayoutDetectionResult:
    """Detect page layout regions (synchronous)."""
    if use_layoutparser:
        return _detect_layout_layoutparser(image)
    return _detect_layout_heuristic(image)


async def detect_layout(
    image: np.ndarray,
    use_layoutparser: bool = True,
) -> LayoutDetectionResult:
    """Detect page layout regions (async)."""
    return await asyncio.to_thread(detect_layout_sync, image, use_layoutparser)


def get_regions_by_type(
    result: LayoutDetectionResult,
    region_type: RegionType,
) -> list[PageRegion]:
    """Return only regions of a given type."""
    return [r for r in result.regions if r.region_type == region_type]


def crop_region(image: np.ndarray, region: PageRegion) -> np.ndarray:
    """Crop image to the region's bounding box."""
    x1, y1, x2, y2 = region.bbox
    return image[y1:y2, x1:x2]
