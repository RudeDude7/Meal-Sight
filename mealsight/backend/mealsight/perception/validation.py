"""validate_image / validate_audio — pre-flight checks run before ever
spending a real API call: format, file size, and (image) minimum pixel
dimensions or (audio) duration. Deliberately cheap and entirely local
(Pillow / mutagen decoding only, no network) so clearly unusable input
never reaches the provider layer at all.
"""

from __future__ import annotations

from io import BytesIO

import mutagen
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


SUPPORTED_AUDIO_FORMATS: frozenset[str] = frozenset({"WAV", "MP3", "M4A", "WEBM"})

# mutagen's own detected-type class name -> this module's format label.
_MUTAGEN_TYPE_TO_FORMAT: dict[str, str] = {"WAVE": "WAV", "MP3": "MP3", "MP4": "M4A"}

# Groq's own documented file-size limit for the free-tier Whisper
# transcription endpoint — a real external constraint, not an arbitrary
# guess, so a caller gets a clear local rejection instead of a 413 from
# the API after the fact.
MAX_AUDIO_FILE_SIZE_MB = 25

# The EBML header ID every WebM/Matroska file starts with. mutagen has
# no WebM/Matroska module at all (see its own format list) — so WEBM is
# recognized by this magic prefix rather than by mutagen.File(), and its
# duration is deliberately NOT parsed: a live-recorded WebM clip
# (e.g. a browser's MediaRecorder output) commonly has an unknown-size
# Segment and no Duration element until the recording is finalized, and
# hand-rolling an EBML parser just for this one field, with zero real
# WEBM fixtures in this project to test it against, is not a trade this
# module makes. A WEBM file's duration is simply not checked locally;
# format and file size still are.
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"


class AudioValidationError(ValueError):
    """Raised by validate_audio for input that's clearly unusable —
    wrong format, too large, too long, or not decodable as audio at
    all. Always carries a message naming the specific problem."""


def _detect_format_and_duration(audio_bytes: bytes) -> tuple[str, float | None]:
    if audio_bytes[: len(_WEBM_MAGIC)] == _WEBM_MAGIC:
        return "WEBM", None

    decoded = mutagen.File(BytesIO(audio_bytes))
    if decoded is None or decoded.info is None:
        raise AudioValidationError("Audio bytes could not be decoded — not a recognizable audio file.")

    format_name = _MUTAGEN_TYPE_TO_FORMAT.get(type(decoded).__name__)
    if format_name is None:
        raise AudioValidationError(
            f"Unsupported audio format {type(decoded).__name__!r} — expected one of "
            f"{sorted(SUPPORTED_AUDIO_FORMATS)}."
        )
    return format_name, float(decoded.info.length)


def detect_audio_format(audio_bytes: bytes) -> str:
    """Returns "WAV"/"MP3"/"M4A"/"WEBM" — the same detection
    validate_audio uses internally, exposed separately since a caller
    that's already validated the bytes (mealsight.perception.processor)
    still needs to know the format, to build a correctly-extensioned
    filename for the transcription provider. Raises AudioValidationError
    under the identical conditions validate_audio's own format check
    does."""
    format_name, _duration = _detect_format_and_duration(audio_bytes)
    return format_name


def validate_audio(audio_bytes: bytes) -> None:
    """Rejects clearly unusable input before spending a real
    transcription API call on it. Raises AudioValidationError, naming
    the specific problem, for anything that fails; returns None (no
    exception) for anything usable.

    Checks, in this order: file size against MAX_AUDIO_FILE_SIZE_MB,
    that the bytes actually decode as one of WAV/MP3/M4A/WEBM at all,
    and — for every format except WEBM, whose duration this module
    deliberately does not parse (see _WEBM_MAGIC's own comment) —
    duration against settings.max_audio_duration_seconds.
    """
    size_mb = len(audio_bytes) / (1024 * 1024)
    if size_mb > MAX_AUDIO_FILE_SIZE_MB:
        raise AudioValidationError(f"Audio is {size_mb:.1f}MB, over the {MAX_AUDIO_FILE_SIZE_MB}MB limit.")

    _format, duration_seconds = _detect_format_and_duration(audio_bytes)

    if duration_seconds is not None and duration_seconds > settings.max_audio_duration_seconds:
        raise AudioValidationError(
            f"Audio is {duration_seconds:.0f}s, over the {settings.max_audio_duration_seconds}s limit."
        )
