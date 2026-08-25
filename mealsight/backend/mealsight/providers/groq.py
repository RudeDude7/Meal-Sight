"""Groq provider: audio transcription against
https://api.groq.com/openai/v1/audio/transcriptions.

KNOWN ISSUE: raw httpx requests to this endpoint have been observed
returning HTTP 403 with a Cloudflare "error code: 1010" body — bot
fingerprinting triggered by a missing or nonstandard User-Agent header,
not an authentication problem. A normal browser-like User-Agent is set
explicitly below to avoid it; if it still happens, transcribe() raises
ProviderUnavailable with a message naming the Cloudflare block
specifically, so it doesn't get mistaken for a bad API key.
"""

from __future__ import annotations

import json
import mimetypes
import time
from typing import Any

import httpx

from mealsight.config.settings import settings
from mealsight.providers.base import AudioProvider, TranscriptionResponse
from mealsight.providers.exceptions import InvalidResponse, ProviderUnavailable
from mealsight.providers.rate_limiter import RateLimiter
from mealsight.providers.retry import request_with_retry
from mealsight.utils.logging import current_trace_id, get_logger

BASE_URL = "https://api.groq.com/openai/v1"

# A normal desktop-browser User-Agent — the specific browser/version doesn't
# matter, only that it looks like a real client to Cloudflare's fingerprinting.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CLOUDFLARE_BLOCK_MARKER = "error code: 1010"


class GroqProvider(AudioProvider):
    def __init__(self, client: httpx.AsyncClient, rate_limiter: RateLimiter) -> None:
        self._client = client
        self._rate_limiter = rate_limiter
        self._logger = get_logger("mealsight.providers.groq")
        # Same process-wide-singleton caveat as MistralProvider's own
        # _call_log — filter by trace_id to scope to one run.
        self._call_log: list[dict[str, Any]] = []

    async def transcribe(self, audio_bytes: bytes, filename: str, model_id: str) -> TranscriptionResponse:
        # Whisper's limit on this account is RPS-only (see settings.MODEL_RATE_LIMITS,
        # tpm=0), so the estimate here only ever affects the request-rate bucket.
        await self._rate_limiter.acquire(model_id, estimated_tokens=0)
        started = time.monotonic()

        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        async def make_request() -> httpx.Response:
            headers = {
                "Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}",
                "User-Agent": USER_AGENT,
            }
            files = {"file": (filename, audio_bytes, content_type)}
            data = {"model": model_id}
            return await self._client.post(
                f"{BASE_URL}/audio/transcriptions", headers=headers, data=data, files=files
            )

        response = await request_with_retry(
            make_request, provider="groq", model_id=model_id, logger=self._logger
        )
        latency_ms = (time.monotonic() - started) * 1000

        if response.status_code == 403 and CLOUDFLARE_BLOCK_MARKER in response.text:
            raise ProviderUnavailable(
                "Groq request blocked by Cloudflare bot protection (error code: 1010) — "
                "this is a fingerprinting block, not an authentication failure.",
                provider="groq",
                model_id=model_id,
            )

        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"Groq returned HTTP {response.status_code}", provider="groq", model_id=model_id
            )

        try:
            payload = response.json()
            text = payload["text"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise InvalidResponse(
                "Unexpected Groq response shape",
                provider="groq",
                model_id=model_id,
                raw_text=response.text,
                cause=exc,
            ) from exc

        self._call_log.append(
            {
                "model_id": model_id,
                # Whisper transcription has no token usage to report —
                # left null rather than fabricated, unlike Mistral's own
                # real per-call usage.
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "latency_ms": round(latency_ms, 2),
                "trace_id": current_trace_id(),
            }
        )

        return TranscriptionResponse(text=text, model_id=model_id, latency_ms=latency_ms)

    def get_call_log(self) -> list[dict[str, Any]]:
        """Every real transcription this provider has made, across every
        run in the process's lifetime. Filter by trace_id
        (mealsight.utils.logging.current_trace_id) to get just one run's
        own calls."""
        return list(self._call_log)
