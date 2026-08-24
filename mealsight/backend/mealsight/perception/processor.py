"""analyze_fridge_photo — the vision perception pipeline: validate the
raw bytes, call the vision provider with the benchmarked (and now
quantity/unit/freshness-extended) prompt, and post-process every
identified item into pantry-ready shape.

Deterministic post-processing; the vision call itself is the only
non-deterministic step, mitigated by temperature=0.0 (mealsight.
providers.mistral's own default for every call it makes).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from pydantic import ValidationError

from mealsight.config.settings import settings
from mealsight.db import get_pantry_db, get_recipe_db
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.pantry.category import resolve_category
from mealsight.pantry.models import PantryItemInput
from mealsight.pantry.shelf_life import load_shelf_life_map
from mealsight.perception.models import IdentifiedItem, RawVisionPerception, VisionPerception
from mealsight.perception.prompt import VISION_PERCEPTION_PROMPT
from mealsight.perception.validation import ImageValidationError, validate_image
from mealsight.providers import ProviderError, get_vision_provider
from mealsight.utils.logging import get_logger

logger = get_logger("mealsight.perception")

# A small, deliberate duplicate of mealsight.providers.mistral's own
# private _strip_code_fences / _CODE_FENCE_RE — the same "duplicate a
# tiny private helper rather than import across a package boundary"
# precedent mealsight.pantry.category already established for a
# different module's private helper.
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

_UNAVAILABLE_NOTE = "Vision analysis was unavailable — continuing without photo-derived pantry items."


def _empty_perception(note: str) -> VisionPerception:
    return VisionPerception(identified_items=[], total_items_found=0, photo_quality="unknown", notes=note)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    match = _CODE_FENCE_RE.match(stripped)
    return match.group(1).strip() if match else stripped


def _parse_raw_response(text: str) -> RawVisionPerception:
    data = json.loads(_strip_code_fences(text))
    return RawVisionPerception.model_validate(data)


async def analyze_fridge_photo(
    image_bytes: bytes,
    pantry_db: Database | None = None,
    recipe_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> VisionPerception:
    """Identifies fridge/pantry contents from a photo, ready to hand
    straight to mealsight.pantry.update_pantry (see this module's own
    to_pantry_item_inputs).

    Validates image_bytes first — format, file size, minimum dimensions,
    all via mealsight.perception.validation.validate_image — and rejects
    clearly unusable input with a structured empty result, before ever
    spending a real API call on it.

    NEVER RAISES: a validation failure, a provider failure (rate limit,
    timeout, unavailable, an unparseable/invalid response), or any other
    unexpected error all return an empty VisionPerception
    (identified_items=[], total_items_found=0) with notes explaining
    what happened, rather than propagating an exception. This is
    deliberate — an agent combining this with audio and text input must
    be able to continue with whatever other input it has even when the
    vision step itself fails outright.

    Every returned item's category is derived locally, via mealsight.
    pantry.category.resolve_category — the model is never asked for a
    category at all (see mealsight.perception.prompt). Every item's
    name is normalized and canonicalized through the exact same
    normalize_ingredient + resolve_canonical pipeline every other part
    of this project uses, so an item reported here merges correctly
    with what update_pantry already has stored rather than creating a
    second row for a synonym of something already there. quantity/unit/
    freshness are passed through exactly as the model reported them —
    null stays null, never guessed at or defaulted to a plausible-
    looking value.
    """
    try:
        validate_image(image_bytes)
    except ImageValidationError as exc:
        logger.warning("vision_perception_image_rejected", reason=str(exc))
        return _empty_perception(str(exc))

    try:
        provider = get_vision_provider()
        response = await provider.analyze_image(image_bytes, VISION_PERCEPTION_PROMPT, settings.VISION_MODEL)
        raw = _parse_raw_response(response.text)
    except (ProviderError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("vision_perception_provider_failed", error=str(exc))
        return _empty_perception(_UNAVAILABLE_NOTE)
    except Exception:
        logger.error("vision_perception_unexpected_failure", exc_info=True)
        return _empty_perception(_UNAVAILABLE_NOTE)

    pantry_db = pantry_db or get_pantry_db()
    if synonym_map is None:
        synonym_map = await load_synonym_map(recipe_db or get_recipe_db())
    shelf_life_map = await load_shelf_life_map(pantry_db)

    items: list[IdentifiedItem] = []
    for raw_item in raw.identified_items:
        canonical = resolve_canonical(normalize_ingredient(raw_item.name), synonym_map)
        category = resolve_category(canonical, shelf_life_map)
        items.append(
            IdentifiedItem(
                name=canonical,
                quantity=raw_item.quantity,
                unit=raw_item.unit,
                category=category,
                freshness=raw_item.freshness,
                confidence=raw_item.confidence,
            )
        )

    return VisionPerception(
        identified_items=items,
        total_items_found=len(items),
        photo_quality=raw.photo_quality,
        notes=raw.notes,
    )


def to_pantry_item_inputs(perception: VisionPerception) -> list[PantryItemInput]:
    """Converts a VisionPerception's identified_items into the exact
    input shape mealsight.pantry.update_pantry expects — this is what
    makes analyze_fridge_photo's output "directly consumable by
    update_pantry" concrete rather than aspirational. The one field
    rename: this schema's freshness becomes PantryItemInput's
    freshness_status, defaulting to PantryItemInput's own "fresh"
    default when the model reported no freshness observation at all —
    never guessed at here either."""
    return [
        PantryItemInput(
            name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            category=item.category,
            **({"freshness_status": item.freshness} if item.freshness is not None else {}),
        )
        for item in perception.identified_items
    ]
