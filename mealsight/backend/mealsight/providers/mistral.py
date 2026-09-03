"""Mistral provider: text completion, structured JSON completion, and
vision (image) analysis, against https://api.mistral.ai/v1.

Temperature defaults to 0.0 everywhere — benchmarking (see
docs/vision_benchmark_report.md) showed meaningful nondeterminism above
that for this task, so callers have to opt into randomness explicitly
rather than get it by default.

Images are sent at native resolution. settings.downscale_images is False
because a benchmark measured F1 dropping from 0.67 to 0.43 when the same
photo was sent downscaled — this module does not resize images, and
should not gain resizing logic without that benchmark being re-run.
"""

from __future__ import annotations

import base64
import json
import re
import time
from types import UnionType
from typing import Any, Union, get_args, get_origin

import httpx
from pydantic import BaseModel, ValidationError

from mealsight.config.settings import settings
from mealsight.providers.base import SchemaT, TextProvider, TextResponse, VisionProvider
from mealsight.providers.exceptions import InvalidResponse, ProviderUnavailable
from mealsight.providers.rate_limiter import RateLimiter
from mealsight.providers.retry import request_with_retry
from mealsight.utils.logging import current_trace_id, get_logger

BASE_URL = "https://api.mistral.ai/v1"

# Measured against a native-resolution aicook photo (~2147 prompt tokens for
# a modest text prompt plus one image) — a flat estimate, not a precise
# tokenizer, since it only needs to be good enough to keep the rate limiter
# roughly honest; reconcile() corrects the budget from the real usage
# afterward.
IMAGE_TOKEN_ESTIMATE = 2000

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_WEBP_RIFF_MAGIC = b"RIFF"
_WEBP_FORMAT_MAGIC = b"WEBP"


def estimate_text_tokens(text: str) -> int:
    """Rough token estimate for rate-limiting purposes: about 4 characters
    per token. Not a real tokenizer — good enough to budget against, not
    to bill against."""
    return max(1, len(text) // 4)


def detect_image_media_type(image_bytes: bytes) -> str:
    """Detects JPEG/PNG/WEBP from the actual byte signature, not a
    filename — a caller could hand this an image with any (or no)
    filename attached. WEBP is a RIFF container, so it's identified by
    two separate magic-byte windows (the "RIFF" tag at offset 0, the
    "WEBP" format tag at offset 8) rather than one contiguous prefix."""
    if image_bytes[: len(_JPEG_MAGIC)] == _JPEG_MAGIC:
        return "image/jpeg"
    if image_bytes[: len(_PNG_MAGIC)] == _PNG_MAGIC:
        return "image/png"
    if image_bytes[:4] == _WEBP_RIFF_MAGIC and image_bytes[8:12] == _WEBP_FORMAT_MAGIC:
        return "image/webp"
    raise ValueError("Unrecognized image format — expected JPEG, PNG, or WEBP magic bytes")


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    match = _CODE_FENCE_RE.match(stripped)
    return match.group(1).strip() if match else stripped


def _parse_and_validate(text: str, schema: type[SchemaT]) -> SchemaT:
    data = json.loads(_strip_code_fences(text))
    return schema.model_validate(data)


def _describe_type(annotation: Any) -> str:
    """A terse, JSON-flavored type name for one field's annotation — the
    building block of _describe_schema below. Deliberately NOT a full
    JSON Schema dump (title/description/constraints per field): this
    exists purely to tell a model the field NAMES and rough SHAPE it
    must produce, at close to zero extra tokens, not to fully specify
    every field the way a real JSON Schema would."""
    origin = get_origin(annotation)

    if origin is Union or origin is UnionType:
        args = get_args(annotation)
        nullable = type(None) in args
        non_none = [a for a in args if a is not type(None)]
        rendered = "|".join(_describe_type(a) for a in non_none)
        return f"{rendered}|null" if nullable else rendered

    if origin is list:
        (item_type,) = get_args(annotation) or (Any,)
        return f"list[{_describe_type(item_type)}]"

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _describe_schema(annotation)

    if isinstance(annotation, type):
        return annotation.__name__.lower()

    return "any"


def _describe_schema(schema: type[BaseModel]) -> str:
    """A compact {"field": type, ...} description of schema's own top-
    level fields (recursing into any nested BaseModel field, so a
    caller like reason.py's own RecipeDecision — six nested Dimension
    Reasoning objects — still gets a real, if terse, shape rather than
    just "object") — cheap enough in tokens to include in every
    complete_json request unconditionally, so no caller can forget to
    tell the model what shape to produce (see this module's own
    complete_json docstring for the real bug this exists to close)."""
    fields = ", ".join(
        f'"{name}": {_describe_type(field.annotation)}' for name, field in schema.model_fields.items()
    )
    return f"{{{fields}}}"


class MistralProvider(TextProvider, VisionProvider):
    def __init__(self, client: httpx.AsyncClient, rate_limiter: RateLimiter) -> None:
        self._client = client
        self._rate_limiter = rate_limiter
        self._logger = get_logger("mealsight.providers.mistral")
        # get_text_provider()/get_vision_provider() return a process-wide
        # singleton (this module's own docstring), so this call log spans
        # every run in the process's lifetime, not just one — present
        # (node 11) filters it down to the current run by trace_id
        # (mealsight.utils.logging.current_trace_id) rather than this
        # provider ever being reset or scoped per run itself.
        self._call_log: list[dict[str, Any]] = []

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.mistral_api_key.get_secret_value()}"}

    async def _send_chat(
        self, body: dict[str, Any], model_id: str, estimated_tokens: int
    ) -> TextResponse:
        await self._rate_limiter.acquire(model_id, estimated_tokens)
        started = time.monotonic()

        async def make_request() -> httpx.Response:
            return await self._client.post(
                f"{BASE_URL}/chat/completions", headers=self._auth_headers(), json=body
            )

        response = await request_with_retry(
            make_request, provider="mistral", model_id=model_id, logger=self._logger
        )
        latency_ms = (time.monotonic() - started) * 1000

        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"Mistral returned HTTP {response.status_code}", provider="mistral", model_id=model_id
            )

        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise InvalidResponse(
                "Unexpected Mistral response shape",
                provider="mistral",
                model_id=model_id,
                raw_text=response.text,
                cause=exc,
            ) from exc

        actual_tokens = int(usage.get("total_tokens", estimated_tokens))
        await self._rate_limiter.reconcile(model_id, actual_tokens, estimated_tokens)

        self._call_log.append(
            {
                "model_id": model_id,
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
                "latency_ms": round(latency_ms, 2),
                "trace_id": current_trace_id(),
            }
        )

        return TextResponse(
            text=text,
            model_id=model_id,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            latency_ms=latency_ms,
        )

    def get_call_log(self) -> list[dict[str, Any]]:
        """Every real completion this provider has made (complete,
        complete_json — including a repair retry, analyze_image), across
        every run in the process's lifetime. Filter by trace_id
        (mealsight.utils.logging.current_trace_id) to get just one run's
        own calls."""
        return list(self._call_log)

    async def complete(
        self,
        prompt: str,
        model_id: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> TextResponse:
        messages: list[dict[str, Any]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {"model": model_id, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        estimated_tokens = estimate_text_tokens(prompt) + (estimate_text_tokens(system) if system else 0)
        return await self._send_chat(body, model_id, estimated_tokens)

    async def complete_json(
        self,
        prompt: str,
        schema: type[SchemaT],
        model_id: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> SchemaT:
        """Requests JSON matching `schema`, validates it, and retries once
        on failure. The request ALWAYS embeds a compact, derived field-
        name-and-type description of `schema` (see _describe_schema) —
        a caller's own prompt text can still explain what each field
        MEANS (worth keeping when it does), but never has to hand-spell
        the JSON shape itself to get a schema-conforming response; a
        caller that forgot to (phase 6.3's own reason.py, on its first
        real run) used to fail validation twice before falling back."""
        schema_description = _describe_schema(schema)
        json_prompt = (
            f"{prompt}\n\nRespond with valid JSON only, matching EXACTLY this shape "
            f"(use null for an absent value, [] for an empty list): {schema_description}\n"
            "No markdown code fences, no other text."
        )
        response = await self.complete(
            json_prompt, model_id, system=system, max_tokens=max_tokens, temperature=temperature
        )

        try:
            return _parse_and_validate(response.text, schema)
        except (json.JSONDecodeError, ValidationError) as first_error:
            self._logger.warning(
                "complete_json_validation_failed", model_id=model_id, attempt=1, error=str(first_error)
            )
            repair_prompt = (
                f"{json_prompt}\n\nYour previous response was invalid: {first_error}\n"
                f"Previous response:\n{response.text}\n\n"
                "Return ONLY corrected valid JSON matching the schema — no markdown fences, no commentary."
            )
            retry_response = await self.complete(
                repair_prompt, model_id, system=system, max_tokens=max_tokens, temperature=temperature
            )
            try:
                return _parse_and_validate(retry_response.text, schema)
            except (json.JSONDecodeError, ValidationError) as second_error:
                raise InvalidResponse(
                    "Model response did not validate against schema after one repair attempt",
                    provider="mistral",
                    model_id=model_id,
                    raw_text=retry_response.text,
                    cause=second_error,
                ) from second_error

    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        model_id: str,
        *,
        system: str | None = None,
    ) -> TextResponse:
        media_type = detect_image_media_type(image_bytes)
        data_url = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"

        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        messages: list[dict[str, Any]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        body: dict[str, Any] = {"model": model_id, "messages": messages, "temperature": 0.0}
        estimated_tokens = estimate_text_tokens(prompt) + IMAGE_TOKEN_ESTIMATE
        return await self._send_chat(body, model_id, estimated_tokens)
