"""Retry policy for provider HTTP calls.

request_with_retry() wraps a function that performs one HTTP request and
returns the raw httpx.Response, retrying it under `settings.llm_max_retries`
/ `settings.llm_retry_backoff` when the failure looks transient:

    - a network error or timeout
    - HTTP 5xx
    - HTTP 429, honoring a Retry-After header when the provider sends one,
      falling back to the normal backoff schedule otherwise

Any other 4xx is never retried — a bad request or an auth failure won't
fix itself by trying again, so this returns the response (or lets the
timeout/connection exception propagate) after exactly one attempt for
those cases, leaving the caller to turn it into the right exception.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from mealsight.config.settings import settings
from mealsight.providers.exceptions import ProviderTimeout, ProviderUnavailable, RateLimitExceeded

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _backoff_delay(attempt: int) -> float:
    backoff = settings.llm_retry_backoff
    if not backoff:
        return 1.0
    index = min(attempt, len(backoff) - 1)
    return float(backoff[index])


def _retry_after_seconds(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        # Retry-After may also be an HTTP-date; that's rare enough for the
        # providers this project talks to that falling back to the normal
        # backoff schedule is simpler than a full date parser here.
        return None


async def request_with_retry(
    make_request: Callable[[], Awaitable[httpx.Response]],
    *,
    provider: str,
    model_id: str,
    logger: Any,
) -> httpx.Response:
    max_retries = settings.llm_max_retries

    for attempt in range(max_retries + 1):
        try:
            response = await make_request()
        except httpx.TimeoutException as exc:
            if attempt >= max_retries:
                raise ProviderTimeout(
                    f"{provider} timed out after {attempt + 1} attempt(s)",
                    provider=provider,
                    model_id=model_id,
                    cause=exc,
                ) from exc
            delay = _backoff_delay(attempt)
            logger.warning(
                "provider_retry", provider=provider, model_id=model_id,
                attempt=attempt + 1, reason="timeout", delay_seconds=delay,
            )
            await asyncio.sleep(delay)
            continue
        except httpx.HTTPError as exc:
            if attempt >= max_retries:
                raise ProviderUnavailable(
                    f"{provider} unreachable after {attempt + 1} attempt(s): {exc}",
                    provider=provider,
                    model_id=model_id,
                    cause=exc,
                ) from exc
            delay = _backoff_delay(attempt)
            logger.warning(
                "provider_retry", provider=provider, model_id=model_id,
                attempt=attempt + 1, reason="connection_error", delay_seconds=delay,
            )
            await asyncio.sleep(delay)
            continue

        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response

        if attempt >= max_retries:
            if response.status_code == 429:
                raise RateLimitExceeded(
                    f"{provider} rate limit exceeded after {attempt + 1} attempt(s)",
                    provider=provider,
                    model_id=model_id,
                )
            raise ProviderUnavailable(
                f"{provider} returned HTTP {response.status_code} after {attempt + 1} attempt(s)",
                provider=provider,
                model_id=model_id,
            )

        if response.status_code == 429:
            retry_after = _retry_after_seconds(response)
            reason = "429_retry_after" if retry_after is not None else "429"
            delay = retry_after if retry_after is not None else _backoff_delay(attempt)
        else:
            delay = _backoff_delay(attempt)
            reason = f"http_{response.status_code}"

        logger.warning(
            "provider_retry", provider=provider, model_id=model_id,
            attempt=attempt + 1, reason=reason, delay_seconds=delay,
        )
        await asyncio.sleep(delay)

    # Unreachable: the loop above always returns or raises before exhausting
    # its range, but mypy needs a terminal statement.
    raise ProviderUnavailable(
        f"{provider} retry loop exhausted unexpectedly", provider=provider, model_id=model_id
    )
