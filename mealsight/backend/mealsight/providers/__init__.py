"""LLM provider abstraction layer.

get_text_provider(), get_vision_provider(), and get_audio_provider() return
process-wide singletons sharing one httpx.AsyncClient and one RateLimiter,
so every provider call in the process is rate-limited against the same
budget per model, and connections are pooled rather than reopened per
call. Call close() during shutdown to release the underlying connections.
"""

from __future__ import annotations

import httpx

from mealsight.providers.base import (
    AudioProvider,
    SchemaT,
    TextProvider,
    TextResponse,
    TranscriptionResponse,
    VisionProvider,
)
from mealsight.providers.exceptions import (
    InvalidResponse,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimitExceeded,
)
from mealsight.providers.groq import GroqProvider
from mealsight.providers.mistral import MistralProvider
from mealsight.providers.rate_limiter import RateLimiter

__all__ = [
    "AudioProvider",
    "SchemaT",
    "TextProvider",
    "TextResponse",
    "TranscriptionResponse",
    "VisionProvider",
    "InvalidResponse",
    "ProviderError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RateLimitExceeded",
    "RateLimiter",
    "get_text_provider",
    "get_vision_provider",
    "get_audio_provider",
    "get_rate_limiter",
    "close",
]

_client: httpx.AsyncClient | None = None
_rate_limiter: RateLimiter | None = None
_mistral_provider: MistralProvider | None = None
_groq_provider: GroqProvider | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    return _client


def get_rate_limiter() -> RateLimiter:
    """Returns the process-wide RateLimiter shared by every provider —
    exposed publicly (not just an internal helper) so diagnostic tooling
    can confirm it's actually engaging, not just trust that it is."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def _get_mistral_provider() -> MistralProvider:
    global _mistral_provider
    if _mistral_provider is None:
        _mistral_provider = MistralProvider(_get_client(), get_rate_limiter())
    return _mistral_provider


def get_text_provider() -> TextProvider:
    return _get_mistral_provider()


def get_vision_provider() -> VisionProvider:
    return _get_mistral_provider()


def get_audio_provider() -> AudioProvider:
    global _groq_provider
    if _groq_provider is None:
        _groq_provider = GroqProvider(_get_client(), get_rate_limiter())
    return _groq_provider


async def close() -> None:
    """Closes the shared httpx client and drops every singleton, so the
    next get_*_provider() call builds fresh ones."""
    global _client, _rate_limiter, _mistral_provider, _groq_provider
    if _client is not None:
        await _client.aclose()
    _client = None
    _rate_limiter = None
    _mistral_provider = None
    _groq_provider = None
