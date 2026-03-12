"""Tests for the preprocessing pipeline."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.services.preprocessing import (
    PreprocessingConfig,
    _binarize,
    _denoise,
    _deskew,
    _remove_borders,
    _to_grayscale,
    preprocess_image_sync,
)


@pytest.fixture
def color_image() -> np.ndarray:
    """A simple BGR color image."""
    return np.random.randint(0, 255, (200, 300, 3), dtype=np.uint8)


@pytest.fixture
def gray_image() -> np.ndarray:
    """A simple grayscale image with text-like content."""
    img = np.full((200, 300), 240, dtype=np.uint8)  # near-white background
    cv2.putText(img, "Hello World", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5, 30, 3)
    return img


def test_to_grayscale_from_color(color_image: np.ndarray):
    result = _to_grayscale(color_image)
    assert len(result.shape) == 2
    assert result.shape[:2] == color_image.shape[:2]


def test_to_grayscale_already_gray(gray_image: np.ndarray):
    result = _to_grayscale(gray_image)
    assert np.array_equal(result, gray_image)


def test_deskew_straight_image(gray_image: np.ndarray):
    result, angle = _deskew(gray_image)
    # A mostly straight image should have small deskew or zero angle
    assert abs(angle) <= 15.0


def test_denoise(gray_image: np.ndarray):
    result = _denoise(gray_image)
    assert result.shape == gray_image.shape
    assert result.dtype == np.uint8


def test_binarize(gray_image: np.ndarray):
    result = _binarize(gray_image)
    # Output should be binary (only 0 and 255)
    unique = np.unique(result)
    assert all(v in (0, 255) for v in unique)


def test_remove_borders(gray_image: np.ndarray):
    # Add a dark border
    bordered = np.zeros((240, 340), dtype=np.uint8)
    bordered[20:220, 20:320] = gray_image
    result = _remove_borders(bordered)
    # Result should be smaller than bordered
    assert result.shape[0] <= bordered.shape[0]
    assert result.shape[1] <= bordered.shape[1]


def test_full_pipeline(color_image: np.ndarray):
    result = preprocess_image_sync(color_image)
    assert result.original_size == (300, 200)
    assert len(result.applied_steps) == 5
    assert "grayscale" in result.applied_steps
    assert "deskew" in result.applied_steps
    assert "denoise" in result.applied_steps
    assert "binarize" in result.applied_steps
    assert "remove_borders" in result.applied_steps


def test_pipeline_config_toggling(color_image: np.ndarray):
    config = PreprocessingConfig(
        grayscale=True,
        deskew=False,
        denoise=False,
        binarize=False,
        remove_borders=False,
    )
    result = preprocess_image_sync(color_image, config)
    assert result.applied_steps == ["grayscale"]
    assert len(result.image.shape) == 2  # grayscale


@pytest.mark.asyncio
async def test_preprocess_image_async(color_image: np.ndarray):
    from backend.services.preprocessing import preprocess_image

    result = await preprocess_image(color_image)
    assert len(result.applied_steps) > 0
