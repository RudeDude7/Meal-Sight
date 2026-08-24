"""Tests for mealsight.perception.validation.validate_text."""

from __future__ import annotations

import pytest

from mealsight.config.settings import settings
from mealsight.perception.validation import TextValidationError, validate_text


def test_normal_text_passes() -> None:
    validate_text("2 servings, 25 minutes, vegetarian.")


def test_oversized_text_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_text_length", 10)

    with pytest.raises(TextValidationError, match="character"):
        validate_text("this text is definitely longer than ten characters")
