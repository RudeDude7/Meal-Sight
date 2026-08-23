"""Exceptions raised by the provider abstraction layer.

Every exception carries the provider name (e.g. "mistral", "groq"), the
model id involved, and the underlying cause when one exists, so a caller
several layers up can log or handle a provider failure without needing to
re-derive which provider and model were involved.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for every exception this package raises."""

    def __init__(
        self, message: str, *, provider: str, model_id: str, cause: BaseException | None = None
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model_id = model_id
        self.cause = cause


class RateLimitExceeded(ProviderError):
    """The provider itself rejected a call for exceeding its rate limit
    (HTTP 429) even after honoring any Retry-After and exhausting retries."""


class ProviderUnavailable(ProviderError):
    """The provider could not be reached or returned a server-side failure
    (HTTP 5xx, a network error, or a known non-standard block such as
    Cloudflare bot fingerprinting) after exhausting retries."""


class InvalidResponse(ProviderError):
    """The provider responded successfully at the HTTP level, but the body
    could not be parsed or did not validate against the expected shape.

    Carries the raw response text so the caller can inspect exactly what
    the model returned when debugging a bad completion.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model_id: str,
        raw_text: str,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, provider=provider, model_id=model_id, cause=cause)
        self.raw_text = raw_text


class ProviderTimeout(ProviderError):
    """A call to the provider timed out after exhausting retries."""
