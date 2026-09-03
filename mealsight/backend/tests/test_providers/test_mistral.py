"""Tests for mealsight.providers.mistral, mocked with respx — no live calls."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from mealsight.config.settings import MODEL_RATE_LIMITS, RateLimitSpec
from mealsight.providers.exceptions import InvalidResponse
from mealsight.providers.mistral import MistralProvider, _describe_schema
from mealsight.providers.rate_limiter import RateLimiter

CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
TEST_MODEL = "test-mistral-model"


class _Ingredient(BaseModel):
    name: str
    quantity: int


@pytest.fixture(autouse=True)
def _register_test_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(MODEL_RATE_LIMITS, TEST_MODEL, RateLimitSpec(rps=1000.0, tpm=1_000_000))


@pytest.fixture
def provider() -> MistralProvider:
    client = httpx.AsyncClient()
    return MistralProvider(client, RateLimiter())


def _chat_response(content: str, *, prompt_tokens: int = 10, completion_tokens: int = 5) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        },
    )


class _Sub(BaseModel):
    applies: bool
    reasoning: str


class _Nested(BaseModel):
    chosen_id: str
    note: str | None
    tags: list[str]
    detail: _Sub


def test_describe_schema_is_a_compact_name_and_type_list_not_a_json_schema_dump() -> None:
    # The exact defect-1 fix: field NAMES and rough TYPES, terse enough
    # to cost near-zero extra tokens — never a full JSON Schema dump
    # (no "title"/"description"/"$defs" keys, no per-field descriptions).
    description = _describe_schema(_Ingredient)

    assert description == '{"name": str, "quantity": int}'
    assert "$defs" not in description
    assert "title" not in description


def test_describe_schema_recurses_into_a_nested_basemodel_field() -> None:
    # RecipeDecision's own real shape (six nested DimensionReasoning
    # objects) is exactly this case — a nested field must still produce
    # a real, if terse, shape, not just the word "object".
    description = _describe_schema(_Nested)

    assert description == (
        '{"chosen_id": str, "note": str|null, "tags": list[str], '
        '"detail": {"applies": bool, "reasoning": str}}'
    )


@respx.mock
async def test_complete_json_embeds_the_schema_so_a_caller_cannot_forget(
    provider: MistralProvider,
) -> None:
    # The literal phase 6.3 bug: a caller whose OWN prompt text never
    # mentions field names must still get a schema-conforming response,
    # because complete_json itself now always tells the model the shape.
    route = respx.post(CHAT_URL)
    route.mock(return_value=_chat_response('{"name": "egg", "quantity": 3}'))

    await provider.complete_json("list an ingredient — no field names given here", _Ingredient, TEST_MODEL)

    sent_body = json.loads(route.calls[0].request.content)
    sent_prompt = sent_body["messages"][-1]["content"]
    assert '"name": str' in sent_prompt
    assert '"quantity": int' in sent_prompt


@respx.mock
async def test_complete_json_parses_clean_json(provider: MistralProvider) -> None:
    respx.post(CHAT_URL).mock(return_value=_chat_response('{"name": "egg", "quantity": 3}'))

    result = await provider.complete_json("list an ingredient", _Ingredient, TEST_MODEL)

    assert result == _Ingredient(name="egg", quantity=3)


@respx.mock
async def test_complete_json_strips_markdown_code_fences(provider: MistralProvider) -> None:
    fenced = '```json\n{"name": "flour", "quantity": 2}\n```'
    respx.post(CHAT_URL).mock(return_value=_chat_response(fenced))

    result = await provider.complete_json("list an ingredient", _Ingredient, TEST_MODEL)

    assert result == _Ingredient(name="flour", quantity=2)


@respx.mock
async def test_complete_json_retries_once_on_schema_violation_then_succeeds(
    provider: MistralProvider,
) -> None:
    route = respx.post(CHAT_URL)
    route.side_effect = [
        _chat_response('{"name": "egg"}'),  # missing required "quantity"
        _chat_response('{"name": "egg", "quantity": 3}'),
    ]

    result = await provider.complete_json("list an ingredient", _Ingredient, TEST_MODEL)

    assert result == _Ingredient(name="egg", quantity=3)
    assert route.call_count == 2


@respx.mock
async def test_complete_json_raises_invalid_response_after_retry_fails(provider: MistralProvider) -> None:
    route = respx.post(CHAT_URL)
    route.side_effect = [
        _chat_response('{"name": "egg"}'),
        _chat_response("still not valid json"),
    ]

    with pytest.raises(InvalidResponse) as exc_info:
        await provider.complete_json("list an ingredient", _Ingredient, TEST_MODEL)

    assert route.call_count == 2
    assert exc_info.value.raw_text == "still not valid json"
    assert exc_info.value.provider == "mistral"
    assert exc_info.value.model_id == TEST_MODEL


@respx.mock
async def test_image_media_type_detected_from_bytes_not_filename(provider: MistralProvider) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"not a real png but starts with the magic bytes"
    route = respx.post(CHAT_URL).mock(return_value=_chat_response("banana, milk"))

    await provider.analyze_image(png_bytes, "what's in this photo?", TEST_MODEL)

    sent_body = json.loads(route.calls[0].request.content)
    image_url = sent_body["messages"][-1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")


@respx.mock
async def test_no_resizing_occurs_bytes_round_trip_exactly(provider: MistralProvider) -> None:
    jpeg_bytes = b"\xff\xd8\xff" + bytes(range(256)) * 4
    route = respx.post(CHAT_URL).mock(return_value=_chat_response("banana, milk"))

    await provider.analyze_image(jpeg_bytes, "what's in this photo?", TEST_MODEL)

    sent_body = json.loads(route.calls[0].request.content)
    image_url = sent_body["messages"][-1]["content"][1]["image_url"]["url"]
    encoded = image_url.removeprefix("data:image/jpeg;base64,")
    assert base64.b64decode(encoded) == jpeg_bytes
