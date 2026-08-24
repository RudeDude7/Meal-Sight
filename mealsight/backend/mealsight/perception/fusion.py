"""merge_perceptions — combines a VisionPerception, an AudioPerception,
and a TextPerception (any of which may be absent) into one
UnifiedMealRequest.

Deliberately free of database access: no ingredient re-canonicalization
against the real synonym table happens here (every ingredient name
arriving at this module has already been canonicalized once, inside
analyze_fridge_photo / analyze_voice_memo / analyze_text_input
themselves) — the one place this module still needs to compare names
across modalities (matching an audio/text-mentioned protein against
what vision actually saw) uses mealsight.matching.normalize_ingredient
alone, which is pure Python with no I/O, deliberately stopping short of
resolve_canonical's synonym-table lookup. A synonym pair that differs
only across modalities (vision says "green onion", audio says
"scallion") would not cross-match here — a real, named limitation this
module's own DB-free constraint creates, not an oversight.

Synchronous and pure: nothing in this module awaits anything or reaches
a database, by design.
"""

from __future__ import annotations

from mealsight.matching.normalize import normalize_ingredient
from mealsight.perception.models import (
    AudioPerception,
    AvailableIngredient,
    DetectedConflict,
    FreshnessAlert,
    ModalityName,
    TextPerception,
    UnifiedMealRequest,
    VisionPerception,
)
from mealsight.user_intelligence.models import UserProfile

# Only "fresh" (case-insensitively) counts as a clean freshness
# observation; anything else the model actually reported (a real
# observation, never invented — see IdentifiedItem's own docstring)
# becomes a freshness alert.
_CLEAN_FRESHNESS = "fresh"

# The one dietary-restriction-vs-category conflict this module detects
# directly, matching the task's own worked example (milk stays in
# available_ingredients under a dairy-free constraint, flagged with a
# note) — deliberately not extended to vegetarian/vegan/gluten-free/etc,
# since mealsight.pantry.category's eight categories can't reliably
# distinguish a restriction-safe ingredient from an unsafe one within
# most of those categories (category="protein" covers both chicken and
# tofu; category="grain" covers both wheat bread and rice).
_DIETARY_CATEGORY_CONFLICTS: dict[str, str] = {"dairy-free": "dairy"}

# Restrictions detectable by keyword against the ingredient's own name,
# for cases specific enough that a name-level match is actually
# reliable (unlike the broader categories above).
_DIETARY_KEYWORD_CONFLICTS: dict[str, frozenset[str]] = {
    "peanut-free": frozenset({"peanut"}),
    "nut-free": frozenset({"peanut", "almond", "walnut", "cashew", "pecan", "hazelnut", "pistachio"}),
    "shellfish-free": frozenset(
        {"shrimp", "prawn", "crab", "lobster", "shellfish", "clam", "mussel", "oyster", "scallop"}
    ),
    "egg-free": frozenset({"egg"}),
    "soy-free": frozenset({"soy", "tofu", "edamame"}),
}

# Non-orderable string fields: when audio and text both state a
# different value, there's no "smaller" or "more restrictive" one to
# pick, so text wins (typed input is more deliberate than speech) and
# the disagreement is still recorded.
_TEXT_PREFERRED_FIELDS: tuple[str, ...] = (
    "cuisine_preference",
    "protein_preference",
    "occasion",
    "mood_or_preference",
)


def _dietary_conflict_note(
    item_name: str, category: str | None, dietary_restrictions: list[str]
) -> str | None:
    for restriction in dietary_restrictions:
        conflict_category = _DIETARY_CATEGORY_CONFLICTS.get(restriction)
        if conflict_category is not None and category == conflict_category:
            return (
                f'This item conflicts with the stated "{restriction}" restriction — kept in '
                "available_ingredients; recipe filtering excludes it, not perception."
            )
        keywords = _DIETARY_KEYWORD_CONFLICTS.get(restriction)
        if keywords and any(keyword in item_name for keyword in keywords):
            return (
                f'This item conflicts with the stated "{restriction}" restriction — kept in '
                "available_ingredients; recipe filtering excludes it, not perception."
            )
    return None


def _build_available_ingredients(
    vision: VisionPerception | None, audio: AudioPerception | None, text: TextPerception | None
) -> tuple[list[AvailableIngredient], list[FreshnessAlert], list[str]]:
    dietary_restrictions = _union_preserving_order(
        audio.dietary_restrictions if audio else [], text.dietary_restrictions if text else []
    )

    available: list[AvailableIngredient] = []
    freshness_alerts: list[FreshnessAlert] = []
    vision_names_normalized: set[str] = set()

    if vision is not None:
        for item in vision.identified_items:
            normalized_name = normalize_ingredient(item.name)
            vision_names_normalized.add(normalized_name)
            note = _dietary_conflict_note(item.name, item.category, dietary_restrictions)
            available.append(
                AvailableIngredient(
                    name=item.name,
                    verified=True,
                    source="vision",
                    quantity=item.quantity,
                    unit=item.unit,
                    category=item.category,
                    freshness=item.freshness,
                    note=note,
                )
            )
            if item.freshness is not None and item.freshness.strip().lower() != _CLEAN_FRESHNESS:
                freshness_alerts.append(FreshnessAlert(name=item.name, freshness=item.freshness))

    # protein_preference is the one field either audio or text uses to
    # name a specific ingredient the user says they have — see this
    # module's own docstring on why a database-free match here is only
    # ever a best-effort one.
    mentionable_sources: tuple[
        tuple[ModalityName, AudioPerception | None], tuple[ModalityName, TextPerception | None]
    ] = (("audio", audio), ("text", text))
    for source, perception in mentionable_sources:
        if perception is None or perception.protein_preference is None:
            continue
        candidate = perception.protein_preference
        normalized_candidate = normalize_ingredient(candidate)
        if not normalized_candidate or normalized_candidate in vision_names_normalized:
            continue
        vision_names_normalized.add(normalized_candidate)
        available.append(
            AvailableIngredient(
                name=normalized_candidate,
                verified=False,
                source=source,
                note=(
                    f"Mentioned by {source} but not seen in the photo — "
                    "the user may know about something off-camera."
                ),
            )
        )

    return available, freshness_alerts, dietary_restrictions


def _union_preserving_order(*lists: list[str]) -> list[str]:
    merged: list[str] = []
    for values in lists:
        for value in values:
            if value not in merged:
                merged.append(value)
    return merged


def _merge_restrictive_numeric(
    field: str, audio_value: int | None, text_value: int | None, conflicts: list[DetectedConflict]
) -> int | None:
    if audio_value is not None and text_value is not None and audio_value != text_value:
        chosen = min(audio_value, text_value)
        conflicts.append(
            DetectedConflict(
                field=field,
                audio_value=audio_value,
                text_value=text_value,
                chosen_value=chosen,
                reason=f"Took the more restrictive (lower) value for {field}.",
            )
        )
        return chosen
    return audio_value if audio_value is not None else text_value


def _merge_text_preferred_string(
    field: str, audio_value: str | None, text_value: str | None, conflicts: list[DetectedConflict]
) -> str | None:
    if audio_value is not None and text_value is not None and audio_value != text_value:
        conflicts.append(
            DetectedConflict(
                field=field,
                audio_value=audio_value,
                text_value=text_value,
                chosen_value=text_value,
                reason=f"{field} is not an orderable field — preferred text over audio (typed input "
                "is more deliberate than speech).",
            )
        )
        return text_value
    return text_value if text_value is not None else audio_value


def merge_perceptions(
    vision: VisionPerception | None,
    audio: AudioPerception | None,
    text: TextPerception | None,
    user_profile: UserProfile | None = None,
) -> UnifiedMealRequest:
    """Combines up to three perception results into one
    UnifiedMealRequest. Pass None for any modality that wasn't gathered
    at all — modalities_received records exactly which of the three
    arguments were non-None, regardless of whether that modality's own
    perception ended up empty (a real "nothing to report" result and a
    gracefully-degraded failure result look identical from here; the
    caller is what actually knows whether a modality was attempted).

    Raises ValueError if vision, audio, and text are all None — at
    least one modality must be present.

    Merge rules, in full:
      - available_ingredients comes from vision alone, PLUS any
        protein_preference audio or text named that vision never saw —
        added flagged verified=False with an explanatory note, never
        silently dropped and never silently treated as confirmed.
      - dietary_restrictions and avoid_ingredients/avoid_dishes union
        across audio and text, deduplicated (both are already
        canonicalized/normalized by the time they reach this module).
      - servings and max_cook_time_minutes: when audio and text both
        state a value and they differ, the LOWER (more restrictive)
        one wins, and the collision is recorded in conflicts_detected
        with both original values. Unspecified by both falls back to
        user_profile.household_size / .preferred_cook_time_minutes
        when a profile was given, otherwise stays null.
      - cuisine_preference, protein_preference, occasion, and mood_or_
        preference are non-orderable strings: a collision between
        audio and text prefers text (typed input is more deliberate
        than speech) and is still recorded.
      - Nothing is ever removed from available_ingredients because of
        a dietary restriction — see UnifiedMealRequest's own docstring.
    """
    if vision is None and audio is None and text is None:
        raise ValueError("merge_perceptions requires at least one modality; all three were None.")

    modalities_received: list[ModalityName] = []
    if vision is not None:
        modalities_received.append("vision")
    if audio is not None:
        modalities_received.append("audio")
    if text is not None:
        modalities_received.append("text")

    available_ingredients, freshness_alerts, dietary_restrictions = _build_available_ingredients(
        vision, audio, text
    )

    avoid_ingredients = _union_preserving_order(
        audio.avoid_ingredients if audio else [], text.avoid_ingredients if text else []
    )
    avoid_dishes = _union_preserving_order(
        audio.avoid_dishes if audio else [], text.avoid_dishes if text else []
    )

    conflicts: list[DetectedConflict] = []

    servings = _merge_restrictive_numeric(
        "servings", audio.servings if audio else None, text.servings if text else None, conflicts
    )
    max_cook_time_minutes = _merge_restrictive_numeric(
        "max_cook_time_minutes",
        audio.max_cook_time_minutes if audio else None,
        text.max_cook_time_minutes if text else None,
        conflicts,
    )

    if servings is None and user_profile is not None:
        servings = user_profile.household_size
    if max_cook_time_minutes is None and user_profile is not None:
        max_cook_time_minutes = user_profile.preferred_cook_time_minutes

    cuisine_preference = _merge_text_preferred_string(
        "cuisine_preference",
        audio.cuisine_preference if audio else None,
        text.cuisine_preference if text else None,
        conflicts,
    )
    protein_preference = _merge_text_preferred_string(
        "protein_preference",
        audio.protein_preference if audio else None,
        text.protein_preference if text else None,
        conflicts,
    )
    occasion = _merge_text_preferred_string(
        "occasion", audio.occasion if audio else None, text.occasion if text else None, conflicts
    )
    mood_or_preference = _merge_text_preferred_string(
        "mood_or_preference",
        audio.mood_or_preference if audio else None,
        text.mood_or_preference if text else None,
        conflicts,
    )

    return UnifiedMealRequest(
        available_ingredients=available_ingredients,
        freshness_alerts=freshness_alerts,
        servings=servings,
        max_cook_time_minutes=max_cook_time_minutes,
        dietary_restrictions=dietary_restrictions,
        cuisine_preference=cuisine_preference,
        avoid_ingredients=avoid_ingredients,
        avoid_dishes=avoid_dishes,
        mood_or_preference=mood_or_preference,
        protein_preference=protein_preference,
        occasion=occasion,
        modalities_received=modalities_received,
        conflicts_detected=conflicts,
    )
