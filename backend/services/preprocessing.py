"""OpenCV-based image preprocessing pipeline for OCR accuracy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class PreprocessingConfig:
    grayscale: bool = True
    deskew: bool = True
    denoise: bool = True
    binarize: bool = True
    remove_borders: bool = True
    target_dpi: int = 300


@dataclass
class PreprocessedPage:
    image: np.ndarray
    original_size: tuple[int, int]
    deskew_angle: float = 0.0
    applied_steps: list[str] = field(default_factory=list)


def _to_grayscale(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _deskew(image: np.ndarray) -> tuple[np.ndarray, float]:
    """Deskew using Hough line detection. Returns (deskewed_image, angle_degrees)."""
    edges = cv2.Canny(image, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=50, maxLineGap=10)

    if lines is None or len(lines) == 0:
        return image, 0.0

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        angles.append(angle)

    median_angle = float(np.median(angles))

    # Clamp to +/-15 degrees to avoid wild rotations
    if abs(median_angle) > 15.0:
        return image, 0.0

    # Skip trivially small angles
    if abs(median_angle) < 0.1:
        return image, 0.0

    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(
        image, rotation_matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, median_angle


def _denoise(image: np.ndarray) -> np.ndarray:
    denoised = cv2.fastNlMeansDenoising(image, h=10)
    return cv2.medianBlur(denoised, 3)


def _binarize(image: np.ndarray) -> np.ndarray:
    """Otsu binarization with adaptive fallback for non-uniform backgrounds."""
    _, otsu = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Check if background is non-uniform by looking at variance in border regions
    h, w = image.shape[:2]
    border_size = max(5, min(h, w) // 20)
    top = image[:border_size, :]
    bottom = image[-border_size:, :]
    left = image[:, :border_size]
    right = image[:, -border_size:]
    border_pixels = np.concatenate([top.ravel(), bottom.ravel(), left.ravel(), right.ravel()])
    variance = float(np.var(border_pixels))

    if variance > 1000:
        # Non-uniform background — use adaptive threshold
        return cv2.adaptiveThreshold(
            image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8
        )
    return otsu


def _remove_borders(image: np.ndarray) -> np.ndarray:
    """Remove dark borders by finding the largest non-full-image contour."""
    inverted = cv2.bitwise_not(image)
    contours, _ = cv2.findContours(inverted, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return image

    h, w = image.shape[:2]
    full_area = h * w

    best_rect = None
    best_area = 0
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        # Skip contours that are the full image
        if area >= full_area * 0.98:
            continue
        if area > best_area:
            best_area = area
            best_rect = (x, y, cw, ch)

    if best_rect is None or best_area < full_area * 0.5:
        return image

    x, y, cw, ch = best_rect
    return image[y : y + ch, x : x + cw]


def preprocess_image_sync(
    image: np.ndarray, config: PreprocessingConfig | None = None
) -> PreprocessedPage:
    """Run the full preprocessing pipeline (CPU-bound, synchronous)."""
    if config is None:
        config = PreprocessingConfig()

    original_size = (image.shape[1], image.shape[0])
    applied_steps: list[str] = []
    deskew_angle = 0.0

    current = image

    if config.grayscale:
        current = _to_grayscale(current)
        applied_steps.append("grayscale")

    if config.deskew:
        current, deskew_angle = _deskew(current)
        applied_steps.append("deskew")

    if config.denoise:
        current = _denoise(current)
        applied_steps.append("denoise")

    if config.binarize:
        current = _binarize(current)
        applied_steps.append("binarize")

    if config.remove_borders:
        current = _remove_borders(current)
        applied_steps.append("remove_borders")

    return PreprocessedPage(
        image=current,
        original_size=original_size,
        deskew_angle=deskew_angle,
        applied_steps=applied_steps,
    )


async def preprocess_image(
    image: np.ndarray, config: PreprocessingConfig | None = None
) -> PreprocessedPage:
    """Async wrapper — runs preprocessing in a thread pool."""
    return await asyncio.to_thread(preprocess_image_sync, image, config)
