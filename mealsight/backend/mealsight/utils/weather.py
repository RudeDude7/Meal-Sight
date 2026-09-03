"""A small, entirely optional wrapper around OpenWeatherMap's Current
Weather Data API, used by mealsight.user_intelligence.context to add a
sixth, weather-derived signal to get_context_signals' own output.

OPTIONAL BY DESIGN, AND SILENT ABOUT IT: settings.openweather_api_key
is an optional field (see mealsight.config.settings), and this whole
module degrades to returning None — never raising, never logging above
a warning — whenever the key is absent, blank, or the API call fails
for any reason (network error, timeout, non-200 response, an
unparseable body). A caller (get_context_signals) treats None exactly
like "no weather data exists", which is exactly what today's behavior
already is without this module. Weather is an enhancement to the
existing five-dimension reasoning prompt, never a dependency of it.

LOCATION: there is no login and no stored user location anywhere in
this system, and the frontend has no geolocation input to report one
with — get_current_weather always resolves to settings.
default_weather_lat/default_weather_lon (a single configured default)
unless a caller explicitly passes lat/lon of its own. See settings.py's
own comment on that pair for why coordinates were chosen over a city
name.

CACHING: the free OpenWeatherMap tier allows 1,000 calls/day, and
weather does not change meaningfully within an hour — an in-memory
dict, keyed by (lat, lon) and checked against WEATHER_CACHE_TTL_SECONDS
via time.monotonic(), is all this needs. No database table: this is
exactly the kind of ephemeral, process-local, non-critical cache
mealsight.api.idempotency.IdempotencyStore and mealsight.api.sessions.
SessionStore already use the same in-process/no-external-store
reasoning for. A failed lookup is cached too, for the same TTL as a
successful one — deliberately, so a misconfigured or exhausted key
doesn't retry the network on every single agent run for the next hour;
see reset_cache() for the test-only escape hatch from this.

RETRY/TIMEOUT: uses mealsight.providers.retry.request_with_retry, the
exact same helper mealsight.seed.recipes_from_mealdb already uses for
its own non-LLM external API (TheMealDB) — provider="openweathermap",
model_id="n/a" (request_with_retry's own model_id parameter is
LLM-specific and unused for logging purposes only here), so this
follows the identical retry/backoff (settings.llm_max_retries/
llm_retry_backoff) and timeout conventions already established for
every other outbound HTTP call in this project, rather than
inventing a second policy.
"""

from __future__ import annotations

import time

import httpx
from pydantic import BaseModel, ConfigDict

from mealsight.config.settings import settings
from mealsight.providers.exceptions import ProviderError
from mealsight.providers.retry import request_with_retry
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.utils.weather")

WEATHER_CACHE_TTL_SECONDS = 3600.0  # 1 hour — weather doesn't change meaningfully faster than this.

# Fahrenheit thresholds for the mood-suggestion mapping below. Chosen as
# round, easily-defensible numbers (a documented judgment call, not a
# benchmark-derived constant like settings' own model thresholds): 50F
# and below reads as genuinely cold to a home cook deciding what to eat,
# 85F and above reads as genuinely hot, and everything between is mild
# enough to carry no strong food-character signal on temperature alone.
_COLD_THRESHOLD_F = 50.0
_HOT_THRESHOLD_F = 85.0

# OpenWeatherMap's own weather[0].main vocabulary is a fixed, documented
# set of strings (Thunderstorm, Drizzle, Rain, Snow, Mist, Smoke, Haze,
# Dust, Fog, Sand, Ash, Squall, Tornado, Clear, Clouds) — these two sets
# are the only ones this mapping treats as "rainy" or "snowy"; everything
# else (Clear, Clouds, Mist, and the rest) carries no condition-based
# signal of its own and falls back to temperature alone.
_RAINY_CONDITIONS = frozenset({"Thunderstorm", "Drizzle", "Rain"})
_SNOWY_CONDITIONS = frozenset({"Snow"})

# The one documented place conditions map to food character — the task's
# own explicit requirement. A SUGGESTION fed into the reasoning prompt as
# context, never a filter: nothing downstream is allowed to exclude a
# recipe because of this string.
MOOD_COLD_RAINY_SNOWY = "warm, hearty, comforting"
MOOD_HOT = "light, cold, fresh"
MOOD_MILD = "no strong signal"


class WeatherSnapshot(BaseModel):
    """What get_current_weather returns on success. temperature_f is
    plain Fahrenheit; conditions is OpenWeatherMap's own human-readable
    description (e.g. "light rain", "clear sky"), lowercased;
    mood_suggestion is one of this module's three documented constants,
    never a value invented by an LLM."""

    model_config = ConfigDict(frozen=True)

    temperature_f: float
    conditions: str
    mood_suggestion: str


def _derive_mood_suggestion(temperature_f: float, condition_main: str) -> str:
    """cold OR rainy OR snowy -> warm/hearty/comforting; hot -> light/
    cold/fresh; otherwise (mild, and neither rainy nor snowy) -> no
    strong signal, stated plainly rather than inventing one. "Cold" and
    "hot" are temperature bands (_COLD_THRESHOLD_F/_HOT_THRESHOLD_F);
    "rainy"/"snowy" are condition-string membership, independent of
    temperature — a 60F rainy day still reads as comforting-food
    weather even though 60F alone would be "mild"."""
    is_cold = temperature_f <= _COLD_THRESHOLD_F
    is_hot = temperature_f >= _HOT_THRESHOLD_F
    is_rainy = condition_main in _RAINY_CONDITIONS
    is_snowy = condition_main in _SNOWY_CONDITIONS

    if is_cold or is_rainy or is_snowy:
        return MOOD_COLD_RAINY_SNOWY
    if is_hot:
        return MOOD_HOT
    return MOOD_MILD


_client: httpx.AsyncClient | None = None
_cache: dict[tuple[float, float], tuple[float, WeatherSnapshot | None]] = {}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    return _client


async def get_current_weather(
    lat: float | None = None,
    lon: float | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> WeatherSnapshot | None:
    """Returns current conditions for (lat, lon), defaulting to
    settings.default_weather_lat/default_weather_lon when omitted.

    NEVER RAISES. Returns None whenever: openweather_api_key is unset or
    blank (checked first, before any network activity at all — a caller
    with no key configured never even touches the cache or the network);
    the API call fails after exhausting retries; or the response can't
    be parsed into a WeatherSnapshot. Every one of those is logged at
    warning (or, for a truly unexpected parse failure, error) level and
    nothing else — this function's whole contract is "give me weather if
    you can, silently give me nothing if you can't."

    Cached per (lat, lon) for WEATHER_CACHE_TTL_SECONDS, success or
    failure alike (see this module's own docstring for why a failure is
    cached too).
    """
    api_key = settings.openweather_api_key
    if api_key is None or not api_key.get_secret_value():
        return None

    resolved_lat = lat if lat is not None else settings.default_weather_lat
    resolved_lon = lon if lon is not None else settings.default_weather_lon
    cache_key = (resolved_lat, resolved_lon)

    cached = _cache.get(cache_key)
    if cached is not None:
        cached_at, snapshot = cached
        if time.monotonic() - cached_at < WEATHER_CACHE_TTL_SECONDS:
            return snapshot

    snapshot = await _fetch_current_weather(
        resolved_lat, resolved_lon, api_key.get_secret_value(), client or _get_client()
    )
    _cache[cache_key] = (time.monotonic(), snapshot)
    return snapshot


async def _fetch_current_weather(
    lat: float, lon: float, api_key: str, client: httpx.AsyncClient
) -> WeatherSnapshot | None:
    url = f"{settings.openweather_base_url}/weather"
    params: dict[str, str | float] = {"lat": lat, "lon": lon, "appid": api_key, "units": "imperial"}

    async def make_request() -> httpx.Response:
        return await client.get(url, params=params)

    try:
        response = await request_with_retry(
            make_request, provider="openweathermap", model_id="n/a", logger=logger
        )
    except ProviderError as exc:
        logger.warning("weather_fetch_failed", error=str(exc))
        return None
    except Exception:
        logger.error("weather_fetch_unexpected_failure", exc_info=True)
        return None

    if response.status_code != 200:
        # A non-retryable status (most likely 401 — an invalid key — or
        # 400/404 for a malformed request) comes back as a plain response
        # here, not an exception; request_with_retry only raises once
        # RETRYABLE_STATUS_CODES are exhausted.
        logger.warning("weather_fetch_non_200", status_code=response.status_code)
        return None

    try:
        payload = response.json()
        temperature_f = float(payload["main"]["temp"])
        weather_entry = payload["weather"][0]
        condition_main = str(weather_entry["main"])
        description = str(weather_entry.get("description", condition_main)).lower()
    except (KeyError, IndexError, TypeError, ValueError):
        logger.warning("weather_parse_failed", exc_info=True)
        return None

    return WeatherSnapshot(
        temperature_f=temperature_f,
        conditions=description,
        mood_suggestion=_derive_mood_suggestion(temperature_f, condition_main),
    )


def reset_cache() -> None:
    """Test-only: clears the in-memory cache so tests don't leak state
    into one another. Never called from production code."""
    _cache.clear()


async def close() -> None:
    """Closes the shared httpx client, mirroring mealsight.providers'
    own close(). Not currently wired into api.app's lifespan — neither
    is mealsight.providers.close(), for the same reason: this process
    exits as a whole on shutdown today, so releasing the connection
    explicitly is a nicety for tests and REPL use, not a correctness
    requirement in production yet."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
