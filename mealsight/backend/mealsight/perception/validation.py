"""validate_image — pre-flight checks run before ever spending a real
vision API call on an image: format, file size, and minimum pixel
dimensions. Deliberately cheap and entirely local (Pillow decoding
only, no network) so clearly unusable input never reaches the provider
layer at all.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from mealsight.config.settings import settings

SUPPORTED_IMAGE_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP"})

# The same "too small to plausibly show real fridge/pantry contents"
# threshold scripts/diagnose_vision.py already established (its own
# SMALL_IMAGE_DIMENSION_PX) — reused as a judgment call, not re-derived
# from any new data.
MIN_IMAGE_DIMENSION_PX = 200


class ImageValidationError(ValueError):
    """Raised by validate_image for input that's clearly unusable —
    wrong format, too large, too small, or not decodable as an image at
    all. Always carries a message naming the specific problem."""


def validate_image(image_bytes: bytes) -> None:
    """Rejects clearly unusable input before spending a real vision API
    call on it. Raises ImageValidationError, naming the specific
    problem, for anything that fails; returns None (no exception) for
    anything usable.

    Checks, in this order: file size against settings.max_image_size_mb
    (cheapest check, and the one most likely to reject a genuinely huge
    upload before ever asking Pillow to decode it), that the bytes
    actually decode as an image at all, that the decoded format is one
    of JPEG/PNG/WEBP, and that both dimensions are at least
    MIN_IMAGE_DIMENSION_PX.
    """
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > settings.max_image_size_mb:
        raise ImageValidationError(
            f"Image is {size_mb:.1f}MB, over the {settings.max_image_size_mb}MB limit."
        )

    try:
        with Image.open(BytesIO(image_bytes)) as img:
            image_format = img.format
            width, height = img.size
    except UnidentifiedImageError as exc:
        raise ImageValidationError("Image bytes could not be decoded — not a recognizable image.") from exc

    if image_format not in SUPPORTED_IMAGE_FORMATS:
        raise ImageValidationError(
            f"Unsupported image format {image_format!r} — expected one of "
            f"{sorted(SUPPORTED_IMAGE_FORMATS)}."
        )

    if width < MIN_IMAGE_DIMENSION_PX or height < MIN_IMAGE_DIMENSION_PX:
        raise ImageValidationError(
            f"Image is {width}x{height}px — below the {MIN_IMAGE_DIMENSION_PX}px minimum on each side."
        )
