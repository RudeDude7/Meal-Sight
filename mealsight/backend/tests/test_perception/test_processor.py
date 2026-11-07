"""Tests for mealsight.perception.processor.analyze_fridge_photo, with
a FakeVisionProvider standing in for the real Mistral call — no live
API call anywhere in this file."""

from __future__ import annotations

import json

import pytest

from mealsight.db.connection import Database
from mealsight.perception import processor as processor_module
from mealsight.perception.processor import analyze_fridge_photo, to_pantry_item_inputs
from mealsight.providers.exceptions import ProviderUnavailable
from tests.test_perception.conftest import FakeVisionProvider, make_jpeg_bytes

_SYNONYMS = {"scallion": "green onion"}


def _patch_provider(monkeypatch: pytest.MonkeyPatch, provider: FakeVisionProvider) -> None:
    monkeypatch.setattr("mealsight.perception.processor.get_vision_provider", lambda: provider)


async def test_valid_response_parses_and_canonicalizes(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    response_json = json.dumps(
        {
            "identified_items": [
                {
                    "name": "scallions",
                    "quantity": 3.0,
                    "unit": "count",
                    "freshness": "fresh",
                    "confidence": "high",
                }
            ],
            "total_items_found": 1,
            "photo_quality": "clear, well-lit",
            "notes": None,
        }
    )
    provider = FakeVisionProvider(text=response_json)
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map=_SYNONYMS)

    assert len(provider.calls) == 1
    assert result.total_items_found == 1
    assert result.identified_items[0].name == "green onion"  # canonicalized, not "scallions"
    assert result.identified_items[0].quantity == 3.0
    assert result.identified_items[0].confidence == "high"


async def test_oversized_image_rejected_before_any_api_call(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    from mealsight.config.settings import settings

    monkeypatch.setattr(settings, "max_image_size_mb", 0.0001)
    provider = FakeVisionProvider(text="{}")
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})

    assert provider.calls == []
    assert result.identified_items == []
    assert result.total_items_found == 0
    assert result.notes is not None


async def test_wrong_format_rejected_before_any_api_call(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    provider = FakeVisionProvider(text="{}")
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(b"this is not an image at all", pantry_db=pantry_db, synonym_map={})

    assert provider.calls == []
    assert result.identified_items == []


async def test_response_missing_quantity_and_unit_still_parses(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    response_json = json.dumps(
        {
            "identified_items": [{"name": "onion", "confidence": "medium"}],
            "total_items_found": 1,
            "photo_quality": "dim lighting",
            "notes": None,
        }
    )
    provider = FakeVisionProvider(text=response_json)
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})

    assert result.identified_items[0].name == "onion"
    assert result.identified_items[0].quantity is None
    assert result.identified_items[0].unit is None
    assert result.identified_items[0].freshness is None


async def test_provider_failure_returns_empty_result_with_note_not_an_exception(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    provider = FakeVisionProvider(
        error=ProviderUnavailable("simulated outage", provider="mistral", model_id="test-model")
    )
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})

    assert result.identified_items == []
    assert result.total_items_found == 0
    assert result.notes is not None
    assert "unavailable" in result.notes.lower()


async def test_invalid_json_response_returns_empty_result_not_an_exception(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    provider = FakeVisionProvider(text="this is not json at all")
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})

    assert result.identified_items == []
    assert result.notes is not None


_ONE_ITEM_JSON = json.dumps(
    {
        "identified_items": [
            {"name": "onion", "quantity": None, "unit": None, "freshness": None, "confidence": "high"}
        ],
        "total_items_found": 1,
        "photo_quality": "clear",
        "notes": None,
    },
    indent=2,
)


@pytest.mark.parametrize(
    "wrapper",
    [
        "{payload}\n```",  # lone trailing fence, observed from ministral-8b-2512 on 30/30 photos
        "```json\n{payload}\n```",
        "```\n{payload}\n```",
        "```json\n{payload}",  # lone leading fence
        "{payload}",
    ],
)
async def test_fenced_json_variants_all_parse(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database, wrapper: str
) -> None:
    provider = FakeVisionProvider(text=wrapper.format(payload=_ONE_ITEM_JSON))
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})

    assert [i.name for i in result.identified_items] == ["onion"]


class _RecordingLogger:
    """Stands in for the module's structlog logger. capture_logs() can't be
    used: whether a module-level logger honors it depends on structlog state
    left behind by earlier tests in the same process."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def _record(self, level: str, event: str, **kwargs: object) -> None:
        self.events.append((level, event, kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self._record("warning", event, **kwargs)

    def error(self, event: str, **kwargs: object) -> None:
        self._record("error", event, **kwargs)

    def info(self, event: str, **kwargs: object) -> None:
        self._record("info", event, **kwargs)


async def test_unparseable_response_logs_raw_head_and_escalates_when_systematic(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    monkeypatch.setattr(processor_module, "_consecutive_parse_failures", 0)
    recorder = _RecordingLogger()
    monkeypatch.setattr(processor_module, "logger", recorder)
    _patch_provider(monkeypatch, FakeVisionProvider(text="x" * 500))
    threshold = processor_module.VISION_PARSE_FAILURE_ESCALATION_THRESHOLD

    for _ in range(threshold):
        result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})
        assert result.identified_items == []

    warnings = [e for e in recorder.events if e[1] == "vision_response_unparseable"]
    errors = [e for e in recorder.events if e[1] == "vision_parsing_failing_systematically"]
    assert len(warnings) == threshold
    assert warnings[0][2]["raw_response_head"] == "x" * 200
    assert [w[2]["consecutive_failures"] for w in warnings] == list(range(1, threshold + 1))
    assert len(errors) == 1
    assert errors[0][0] == "error"


async def test_successful_parse_resets_the_consecutive_failure_count(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    monkeypatch.setattr(processor_module, "_consecutive_parse_failures", 2)
    _patch_provider(monkeypatch, FakeVisionProvider(text=_ONE_ITEM_JSON))

    await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})

    assert processor_module._consecutive_parse_failures == 0


async def test_categories_are_locally_derived_not_from_the_model(
    monkeypatch: pytest.MonkeyPatch, pantry_db: Database
) -> None:
    # The model's response can't include "category" at all (RawIdentifiedItem
    # has no such field), but an extra "category" key smuggled into the raw
    # JSON must still be ignored — pydantic drops unknown fields by default,
    # and resolve_category is what actually decides the real value.
    response_json = json.dumps(
        {
            "identified_items": [{"name": "chicken", "category": "made up nonsense", "confidence": "high"}],
            "total_items_found": 1,
            "photo_quality": "clear",
            "notes": None,
        }
    )
    provider = FakeVisionProvider(text=response_json)
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})

    assert result.identified_items[0].category == "protein"


async def test_to_pantry_item_inputs_shape(monkeypatch: pytest.MonkeyPatch, pantry_db: Database) -> None:
    response_json = json.dumps(
        {
            "identified_items": [
                {"name": "milk", "quantity": 1.0, "unit": "liter", "freshness": "fresh", "confidence": "high"}
            ],
            "total_items_found": 1,
            "photo_quality": "clear",
            "notes": None,
        }
    )
    provider = FakeVisionProvider(text=response_json)
    _patch_provider(monkeypatch, provider)

    result = await analyze_fridge_photo(make_jpeg_bytes(), pantry_db=pantry_db, synonym_map={})
    pantry_items = to_pantry_item_inputs(result)

    assert len(pantry_items) == 1
    assert pantry_items[0].name == "milk"
    assert pantry_items[0].freshness_status == "fresh"
    assert pantry_items[0].category == "dairy"
