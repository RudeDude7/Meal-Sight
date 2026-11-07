"""Tests for mealsight.config.settings."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from mealsight.config.settings import DEFAULT_ENV_FILE, RateLimitSpec, load_settings


@pytest.fixture(autouse=True)
def _no_ambient_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests assert where a value comes FROM (a file, or a real variable). They must not be at the mercy
    of keys that happen to be exported in the environment running them (a developer shell, or CI)."""
    for name in ("MISTRAL_API_KEY", "GROQ_API_KEY", "OPENWEATHER_API_KEY"):
        monkeypatch.delenv(name, raising=False)


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


def test_default_env_file_is_absolute_and_cwd_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    # DEFAULT_ENV_FILE is computed once at import time from the settings
    # module's own __file__, not from the process's current working
    # directory — so it stays the same absolute path no matter where a
    # caller's CWD happens to be when load_settings() actually runs.
    assert DEFAULT_ENV_FILE.is_absolute()
    monkeypatch.chdir(Path("/"))
    # importlib.import_module, not `from mealsight.config import settings`,
    # to get the real settings SUBMODULE back — mealsight.config's own
    # __init__.py re-exports the settings INSTANCE under the same name
    # ("settings"), which shadows the submodule as a package attribute.
    settings_module = importlib.import_module("mealsight.config.settings")

    assert settings_module.DEFAULT_ENV_FILE == DEFAULT_ENV_FILE


def test_settings_loads_correctly_from_a_cwd_outside_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("MISTRAL_API_KEY=from-file-mistral\nGROQ_API_KEY=from-file-groq\n")

    outside_dir = tmp_path / "somewhere" / "else"
    outside_dir.mkdir(parents=True)
    monkeypatch.chdir(outside_dir)

    settings = load_settings(env_file=env_path)

    assert settings.mistral_api_key.get_secret_value() == "from-file-mistral"
    assert settings.groq_api_key.get_secret_value() == "from-file-groq"


def test_real_env_var_overrides_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("MISTRAL_API_KEY=from-file-mistral\nGROQ_API_KEY=from-file-groq\n")
    monkeypatch.setenv("MISTRAL_API_KEY", "from-real-env-var")

    settings = load_settings(env_file=env_path)

    assert settings.mistral_api_key.get_secret_value() == "from-real-env-var"
    # groq wasn't overridden by a real env var, so it still comes from the file.
    assert settings.groq_api_key.get_secret_value() == "from-file-groq"


def test_blank_required_secret_raises_naming_variable_and_searched_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("MISTRAL_API_KEY=\nGROQ_API_KEY=from-file-groq\n")

    with pytest.raises(RuntimeError) as exc_info:
        load_settings(env_file=env_path)

    message = str(exc_info.value)
    assert "MISTRAL_API_KEY" in message
    assert "GROQ_API_KEY" not in message
    assert str(env_path) in message


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

    extraction = settings.get_rate_limit("ministral-8b-2512")
    assert extraction == RateLimitSpec(rps=3.13, tpm=625_000)

    # Retired by Mistral (2026-10); deliberately no longer configured.
    with pytest.raises(KeyError, match="mistral-medium-2505"):
        settings.get_rate_limit("mistral-medium-2505")

    with pytest.raises(KeyError, match="unknown-model-xyz"):
        settings.get_rate_limit("unknown-model-xyz")
