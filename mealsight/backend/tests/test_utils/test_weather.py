"""Tests for mealsight.utils.weather, mocked with respx — no live calls.

settings.openweather_api_key is genuinely set in this project's own
.env (so the module's real, non-mocked degrade-on-missing-key path is
exercised separately, live, as part of this task's own verification
run) — every test here that needs "no key configured" explicitly
monkeypatches it to None rather than relying on it being unset."""

from __future__ import annotations

import httpx
import pytest
import respx

from mealsight.config.settings import settings
from mealsight.providers.exceptions import ProviderError
from mealsight.utils import weather

WEATHER_URL = f"{settings.openweather_base_url}/weather"


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    weather.reset_cache()
    yield
    weather.reset_cache()


def _owm_response(*, temp_f: float, main: str, description: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "main": {"temp": temp_f},
            "weather": [{"main": main, "description": description}],
        },
    )


@respx.mock
async def test_missing_api_key_returns_none_without_any_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Zero routes registered on purpose: if get_current_weather attempted
    # any HTTP call at all, respx would raise on the unmocked request and
    # fail this test — the absence of that failure IS the proof no
    # network call was made.
    monkeypatch.setattr(settings, "openweather_api_key", None)
    result = await weather.get_current_weather()
    assert result is None


@respx.mock
async def test_successful_call_returns_temperature_conditions_and_mood() -> None:
    respx.get(WEATHER_URL).mock(
        return_value=_owm_response(temp_f=72.0, main="Clear", description="clear sky")
    )
    result = await weather.get_current_weather()
    assert result is not None
    assert result.temperature_f == 72.0
    assert result.conditions == "clear sky"
    assert result.mood_suggestion == weather.MOOD_MILD


@respx.mock
async def test_api_failure_after_retries_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_max_retries", 0)
    respx.get(WEATHER_URL).mock(return_value=httpx.Response(500))
    result = await weather.get_current_weather()
    assert result is None


@respx.mock
async def test_non_200_non_retryable_status_degrades_to_none() -> None:
    respx.get(WEATHER_URL).mock(return_value=httpx.Response(401, json={"message": "invalid key"}))
    result = await weather.get_current_weather()
    assert result is None


@respx.mock
async def test_unparseable_body_degrades_to_none() -> None:
    respx.get(WEATHER_URL).mock(return_value=httpx.Response(200, json={"unexpected": "shape"}))
    result = await weather.get_current_weather()
    assert result is None


@respx.mock
async def test_network_error_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_max_retries", 0)
    respx.get(WEATHER_URL).mock(side_effect=httpx.ConnectError("boom"))
    result = await weather.get_current_weather()
    assert result is None


@respx.mock
async def test_cache_prevents_repeat_calls_within_ttl() -> None:
    route = respx.get(WEATHER_URL).mock(
        return_value=_owm_response(temp_f=72.0, main="Clear", description="clear sky")
    )
    first = await weather.get_current_weather()
    second = await weather.get_current_weather()
    assert route.call_count == 1
    assert first == second


@respx.mock
async def test_cache_is_bypassed_once_ttl_expires() -> None:
    route = respx.get(WEATHER_URL).mock(
        return_value=_owm_response(temp_f=72.0, main="Clear", description="clear sky")
    )
    await weather.get_current_weather()

    # Backdate the cache entry directly rather than monkeypatching the
    # real time.monotonic globally — simpler and doesn't risk affecting
    # anything else running during the test.
    cache_key = (settings.default_weather_lat, settings.default_weather_lon)
    recorded_at, snapshot = weather._cache[cache_key]
    weather._cache[cache_key] = (recorded_at - weather.WEATHER_CACHE_TTL_SECONDS - 1, snapshot)

    await weather.get_current_weather()

    assert route.call_count == 2


@respx.mock
async def test_a_failed_lookup_is_also_cached_for_the_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_max_retries", 0)
    route = respx.get(WEATHER_URL).mock(return_value=httpx.Response(500))
    first = await weather.get_current_weather()
    second = await weather.get_current_weather()
    assert first is None
    assert second is None
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("temp_f", "condition_main", "expected_mood"),
    [
        (20.0, "Clear", weather.MOOD_COLD_RAINY_SNOWY),  # cold
        (95.0, "Clear", weather.MOOD_HOT),  # hot
        (68.0, "Rain", weather.MOOD_COLD_RAINY_SNOWY),  # rainy, mild temperature
        (68.0, "Snow", weather.MOOD_COLD_RAINY_SNOWY),  # snowy, mild temperature
        (68.0, "Thunderstorm", weather.MOOD_COLD_RAINY_SNOWY),  # stormy counts as rainy
        (68.0, "Clear", weather.MOOD_MILD),  # genuinely mild, no strong signal
        (68.0, "Clouds", weather.MOOD_MILD),  # cloudy but not rainy/snowy stays mild
    ],
)
def test_condition_and_temperature_map_to_the_documented_mood(
    temp_f: float, condition_main: str, expected_mood: str
) -> None:
    assert weather._derive_mood_suggestion(temp_f, condition_main) == expected_mood


def test_mild_weather_produces_no_strong_signal_not_a_fabricated_one() -> None:
    mood = weather._derive_mood_suggestion(70.0, "Clouds")
    assert mood == "no strong signal"


async def test_explicit_lat_lon_bypasses_the_configured_default() -> None:
    with respx.mock() as router:
        router.get(WEATHER_URL).mock(
            return_value=_owm_response(temp_f=50.0, main="Clear", description="clear sky")
        )
        await weather.get_current_weather(lat=51.5074, lon=-0.1278)
        request = router.calls.last.request
        assert "lat=51.5074" in str(request.url)
        assert "lon=-0.1278" in str(request.url)


async def test_provider_error_is_caught_not_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(*_args: object, **_kwargs: object) -> httpx.Response:
        raise ProviderError("simulated", provider="openweathermap", model_id="n/a")

    monkeypatch.setattr(weather, "request_with_retry", _boom)
    result = await weather.get_current_weather()
    assert result is None
