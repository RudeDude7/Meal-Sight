"""Tests for mealsight.config.settings."""

from __future__ import annotations

import pytest

from mealsight.config.settings import RateLimitSpec, load_settings


def test_settings_loads_from_monkeypatched_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    settings = load_settings(env_file=None)

    assert settings.mistral_api_key.get_secret_value() == "test-mistral-key"
    assert settings.groq_api_key.get_secret_value() == "test-groq-key"
    assert settings.openweather_api_key is None


def test_missing_required_secret_raises_naming_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        load_settings(env_file=None)

    assert "MISTRAL_API_KEY" in str(exc_info.value)
    assert "GROQ_API_KEY" in str(exc_info.value)


def test_repr_redacts_every_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "super-secret-mistral-value")
    monkeypatch.setenv("GROQ_API_KEY", "super-secret-groq-value")
    monkeypatch.setenv("OPENWEATHER_API_KEY", "super-secret-weather-value")

    settings = load_settings(env_file=None)
    rendered = repr(settings)

    assert "super-secret-mistral-value" not in rendered
    assert "super-secret-groq-value" not in rendered
    assert "super-secret-weather-value" not in rendered
    assert "mistral_api_key=<redacted>" in rendered
    assert "groq_api_key=<redacted>" in rendered
    assert "openweather_api_key=<redacted>" in rendered
    # str() should redact the same way, since the CLI/logs might use either
    assert str(settings) == rendered


def test_rate_limit_specs_retrievable_per_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    settings = load_settings(env_file=None)

    medium = settings.get_rate_limit("mistral-medium-2505")
    assert medium == RateLimitSpec(rps=0.42, tpm=375_000)

    extraction = settings.get_rate_limit("ministral-8b-2512")
    assert extraction == RateLimitSpec(rps=3.13, tpm=625_000)

    with pytest.raises(KeyError, match="unknown-model-xyz"):
        settings.get_rate_limit("unknown-model-xyz")
