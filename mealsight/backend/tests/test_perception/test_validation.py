"""Tests for mealsight.perception.validation.validate_image."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from mealsight.config.settings import settings
from mealsight.perception.validation import ImageValidationError, validate_image
from tests.test_perception.conftest import make_jpeg_bytes, make_webp_bytes


def test_valid_jpeg_passes() -> None:
    validate_image(make_jpeg_bytes())


def test_valid_webp_passes() -> None:
    validate_image(make_webp_bytes())


def test_oversized_image_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_image_size_mb", 0.0001)

    with pytest.raises(ImageValidationError, match="MB"):
        validate_image(make_jpeg_bytes())


def test_wrong_format_is_rejected() -> None:
    # A real, decodable GIF — Pillow reads it fine, but GIF isn't one of
    # the three formats this pipeline accepts.
    buffer = BytesIO()
    Image.new("RGB", (400, 400), color=(200, 200, 200)).save(buffer, format="GIF")

    with pytest.raises(ImageValidationError, match="format"):
        validate_image(buffer.getvalue())


def test_undecodable_bytes_are_rejected() -> None:
    with pytest.raises(ImageValidationError):
        validate_image(b"this is not an image at all")


def test_too_small_dimensions_are_rejected() -> None:
    with pytest.raises(ImageValidationError, match="minimum"):
        validate_image(make_jpeg_bytes(width=50, height=50))
