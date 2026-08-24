"""update_preferences / remove_preference — writes into the user_profile
key/value table, validating each preference_type's value against a known
field set and, per field, a real type/range/enum check, before it's ever
written.

dietary_restrictions and disliked_ingredients are additive: repeated
calls append and deduplicate rather than replace, and disliked
ingredients are canonicalized through the exact same normalize_ingredient
+ resolve_canonical pipeline mealsight.pantry uses, so "scallions" and
"green onion" collapse to one stored entry. Every other field is scalar
and replaces on write.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from mealsight.db import get_recipe_db, get_user_db
from mealsight.db.connection import Database
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.user_intelligence.models import (
    ADDITIVE_PREFERENCE_TYPES,
    BudgetSensitivity,
    CookingSkill,
    PreferenceType,
    UserProfile,
)
from mealsight.user_intelligence.profile import get_user_profile

_KNOWN_PREFERENCE_TYPES: tuple[str, ...] = get_args(PreferenceType)
_COOKING_SKILLS: tuple[str, ...] = get_args(CookingSkill)
_BUDGET_SENSITIVITIES: tuple[str, ...] = get_args(BudgetSensitivity)


async def _write_value(user_db: Database, key: str, value: Any) -> None:
    await user_db.execute(
        "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
        (key, json.dumps(value)),
    )


async def _read_value(user_db: Database, key: str) -> Any | None:
    row = await user_db.fetch_one("SELECT value FROM user_profile WHERE key = ?", (key,))
    return json.loads(row["value"]) if row is not None else None


def _as_string_list(preference_type: str, value: Any) -> list[str]:
    if isinstance(value, str):
        candidates: list[Any] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        candidates = list(value)
    else:
        raise ValueError(f"{preference_type} expects a string or a list of strings, got {value!r}.")

    cleaned = [item.strip() for item in candidates if isinstance(item, str) and item.strip()]
    if not cleaned:
        raise ValueError(f"{preference_type} expects at least one non-empty string.")
    return cleaned


def _validate_scalar(preference_type: str, value: Any) -> Any:
    if preference_type == "household_size":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"household_size must be a positive integer, got {value!r}.")
        return value
    if preference_type == "preferred_cook_time_minutes":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"preferred_cook_time_minutes must be a positive integer, got {value!r}.")
        return value
    if preference_type == "cooking_skill":
        if value not in _COOKING_SKILLS:
            raise ValueError(f"cooking_skill must be one of {list(_COOKING_SKILLS)}, got {value!r}.")
        return value
    if preference_type == "budget_sensitivity":
        if value not in _BUDGET_SENSITIVITIES:
            raise ValueError(
                f"budget_sensitivity must be one of {list(_BUDGET_SENSITIVITIES)}, got {value!r}."
            )
        return value
    # preference_type == "protein_preference": any string, or null to clear it.
    if value is not None and not isinstance(value, str):
        raise ValueError(f"protein_preference must be a string or null, got {value!r}.")
    return value


async def _canonicalize_dislikes(
    values: list[str], synonym_map: Mapping[str, str] | None
) -> list[str]:
    if synonym_map is None:
        synonym_map = await load_synonym_map(get_recipe_db())
    return [resolve_canonical(normalize_ingredient(v), synonym_map) for v in values]


async def update_preferences(
    preference_type: str,
    value: Any,
    user_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> UserProfile:
    """Writes one preference and returns the full, updated profile.

    dietary_restrictions and disliked_ingredients are ADDITIVE: value may
    be a single string or a list of strings, each is appended to
    whatever is already stored (never replacing it), and the result is
    deduplicated. disliked_ingredients are canonicalized first — the
    same normalize_ingredient + resolve_canonical pipeline
    mealsight.pantry uses — so a synonym of something already disliked
    ("green onion" when "scallions" is already stored) doesn't add a
    second entry.

    Every other field replaces on write: household_size and
    preferred_cook_time_minutes must be positive integers, cooking_skill
    and budget_sensitivity must be one of their accepted literal values
    (mealsight.user_intelligence.models.CookingSkill / BudgetSensitivity),
    protein_preference accepts any string or null (to clear it).

    Raises ValueError — naming the accepted field names, or the accepted
    values/range for the specific field — for an unknown preference_type
    or an invalid value. This module has no MCP layer of its own to turn
    that into a structured error result instead.
    """
    if preference_type not in _KNOWN_PREFERENCE_TYPES:
        raise ValueError(
            f"{preference_type!r} is not a known preference field. "
            f"Accepted: {sorted(_KNOWN_PREFERENCE_TYPES)}."
        )
    user_db = user_db or get_user_db()

    if preference_type in ADDITIVE_PREFERENCE_TYPES:
        additions = _as_string_list(preference_type, value)
        if preference_type == "disliked_ingredients":
            additions = await _canonicalize_dislikes(additions, synonym_map)
        else:
            additions = [item.lower() for item in additions]
        existing = await _read_value(user_db, preference_type) or []
        merged = list(dict.fromkeys([*existing, *additions]))
        await _write_value(user_db, preference_type, merged)
    else:
        validated = _validate_scalar(preference_type, value)
        await _write_value(user_db, preference_type, validated)

    return await get_user_profile(user_db)


async def remove_preference(
    preference_type: str,
    value: str,
    user_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> UserProfile:
    """Removes one entry from an additive field (dietary_restrictions or
    disliked_ingredients) — the only way to shrink either list, since
    update_preferences only ever appends. A value not currently present
    is a no-op, not an error: the profile is returned unchanged rather
    than failing on a removal that's already effectively satisfied.

    Raises ValueError, naming the two valid fields, if preference_type
    isn't one of the additive fields.
    """
    if preference_type not in ADDITIVE_PREFERENCE_TYPES:
        raise ValueError(
            f"remove_preference only supports {sorted(ADDITIVE_PREFERENCE_TYPES)}, got {preference_type!r}."
        )
    user_db = user_db or get_user_db()

    if preference_type == "disliked_ingredients":
        [target] = await _canonicalize_dislikes([value], synonym_map)
    else:
        target = value.strip().lower()

    existing = await _read_value(user_db, preference_type) or []
    remaining = [item for item in existing if item != target]
    await _write_value(user_db, preference_type, remaining)

    return await get_user_profile(user_db)
