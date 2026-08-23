"""MealSight application settings, loaded from the environment (and `.env`).

Import-time behavior: instantiating the module-level `settings` singleton
fails fast with a `RuntimeError` naming the missing variable(s) if a
required secret isn't set, instead of letting a half-configured app start
and fail confusingly later on the first API call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/mealsight/config/settings.py -> backend/mealsight -> backend -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_DATA_DIR = REPO_ROOT / "data"


class RateLimitSpec(BaseModel):
    """A per-model rate limit, as reported by the provider's console for
    this account. Consumed directly by the rate limiter."""

    model_config = ConfigDict(frozen=True)

    rps: float
    tpm: int


# Sourced from the Mistral console (and Groq, for Whisper) for this account.
# These are real limits, not placeholders — the rate limiter must respect them.
MODEL_RATE_LIMITS: dict[str, RateLimitSpec] = {
    "mistral-medium-2505": RateLimitSpec(rps=0.42, tpm=375_000),
    "ministral-8b-2512": RateLimitSpec(rps=3.13, tpm=625_000),
    "whisper-large-v3-turbo": RateLimitSpec(rps=20 / 60, tpm=0),
}


class Settings(BaseSettings):
    """Central configuration for the MealSight backend.

    Every field here is either a secret loaded from the environment, a
    benchmark-derived constant, or a tunable threshold — never business
    logic. See the class docstring on each section below for provenance.
    """

    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "production"] = "development"

    # --- Required secrets -------------------------------------------------
    mistral_api_key: SecretStr
    groq_api_key: SecretStr

    # --- Optional / deferred secrets ---------------------------------------
    # OpenWeatherMap integration is deferred; the field exists so config
    # loading doesn't need to change when that feature is built.
    openweather_api_key: SecretStr | None = None

    # --- Model configuration (benchmark-derived, see docs/VISION_FINDINGS.md) ---
    vision_model: str = "mistral-medium-2505"  # F1 0.64 on aicook eval set; best of 3 tested
    extraction_model: str = "ministral-8b-2512"  # 3.13 RPS, sufficient for structured extraction
    reasoning_model: str = "mistral-medium-2505"
    audio_model: str = "whisper-large-v3-turbo"

    # Images are sent at native resolution. The benchmark showed F1 dropping
    # from 0.67 to 0.43 when the same photo was downscaled to 25% — do not
    # "optimize" this to save bandwidth/tokens without re-running that
    # benchmark, it directly costs recommendation accuracy.
    downscale_images: bool = False

    # --- Matching thresholds ------------------------------------------------
    min_ingredient_match: float = 0.5
    substitution_match_weight: float = 0.7
    critical_missing_penalty: float = 0.3

    # --- Freshness ------------------------------------------------------------
    expiring_soon_days: int = 3
    stale_pantry_item_days: int = 14

    # --- Nutrition --------------------------------------------------------------
    high_protein_threshold_g: float = 25
    low_carb_threshold_g: float = 30
    low_calorie_threshold: float = 400

    # --- Repetition ---------------------------------------------------------------
    repetition_window_days: int = 7
    max_same_protein_per_week: int = 3

    # --- Input limits -------------------------------------------------------------
    max_image_size_mb: float = 10
    max_audio_duration_seconds: int = 300
    max_text_length: int = 2000

    # --- Retry policy -----------------------------------------------------------
    llm_max_retries: int = 3
    llm_retry_backoff: list[int] = Field(default_factory=lambda: [2, 5, 10])
    api_max_retries: int = 2
    api_retry_backoff: list[int] = Field(default_factory=lambda: [1, 3])

    # --- Database paths --------------------------------------------------------
    pantry_db_path: Path = DEFAULT_DATA_DIR / "pantry.db"
    recipes_db_path: Path = DEFAULT_DATA_DIR / "recipes.db"
    user_intelligence_db_path: Path = DEFAULT_DATA_DIR / "user_intelligence.db"

    # --- External APIs --------------------------------------------------------
    themealdb_base_url: str = "https://www.themealdb.com/api/json/v1/1"

    def get_rate_limit(self, model_id: str) -> RateLimitSpec:
        """Looks up the rate limit for a model by id.

        Raises KeyError (naming the model) rather than returning a default,
        since silently rate-limiting an unknown model at some made-up
        default is worse than failing loudly during development.
        """
        try:
            return MODEL_RATE_LIMITS[model_id]
        except KeyError as exc:
            raise KeyError(f"No rate limit configured for model {model_id!r}") from exc

    def __repr__(self) -> str:
        parts: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr) or "api_key" in name or "secret" in name:
                parts.append(f"{name}=<redacted>")
            else:
                parts.append(f"{name}={value!r}")
        return f"{type(self).__name__}({', '.join(parts)})"

    __str__ = __repr__


def load_settings(env_file: str | Path | None = DEFAULT_ENV_FILE) -> Settings:
    """Builds a `Settings` instance, translating a missing-secret
    `ValidationError` into a `RuntimeError` that names the exact
    environment variable(s) that need to be set.

    `env_file` is exposed as a parameter (rather than always reading the
    module-level default) so tests can point it at `None` to isolate
    environment-variable behavior from whatever `.env` happens to be on
    disk.
    """
    try:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        missing = sorted(
            {str(error["loc"][0]).upper() for error in exc.errors() if error["type"] == "missing"}
        )
        if missing:
            raise RuntimeError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set them in your shell or in .env."
            ) from exc
        raise


settings = load_settings()
