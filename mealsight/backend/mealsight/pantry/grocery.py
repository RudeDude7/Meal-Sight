"""create_grocery_list / get_grocery_list — turns each recipe's missing
ingredients into one deduplicated, store-organized grocery list, and
reads one back.

Deterministic, no LLM calls. Cost estimation is explicitly out of scope
— grocery_lists.estimated_total_cost is left null everywhere in this
module, since no price data exists anywhere in this project to base a
real number on; fabricating one would be worse than leaving it empty.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from mealsight.db import get_pantry_db, get_recipe_db
from mealsight.db.connection import Database
from mealsight.matching.models import Importance
from mealsight.matching.normalize import normalize_ingredient
from mealsight.matching.synonyms import load_synonym_map, resolve_canonical
from mealsight.pantry._datetime_utils import parse_sqlite_timestamp
from mealsight.pantry.category import Category, resolve_category
from mealsight.pantry.models import (
    GroceryList,
    GroceryListItem,
    GroceryListSection,
    GroceryQuantity,
    GrocerySection,
    RecipeMissingIngredients,
)
from mealsight.pantry.shelf_life import ShelfLifeEntry, load_shelf_life_map

# Fixed display order — only sections that actually have at least one
# item end up in the returned/persisted GroceryList.
SECTION_ORDER: tuple[GrocerySection, ...] = (
    "produce",
    "protein",
    "dairy",
    "bakery",
    "pantry",
    "frozen",
    "spices",
    "other",
)

# mealsight.pantry.category.resolve_category's eight categories map onto
# this module's eight store sections — every one of resolve_category's
# possible outputs is a key here, so this lookup itself never needs an
# "other" fallback (resolve_category already provides one of its own).
CATEGORY_TO_SECTION: dict[Category, GrocerySection] = {
    "protein": "protein",
    "vegetable": "produce",
    "fruit": "produce",
    "dairy": "dairy",
    "grain": "pantry",
    "condiment": "pantry",
    "spice": "spices",
    "other": "other",
}

# Common staples a real kitchen usually already has open, even if a
# photo never caught them — flagged to verify rather than assumed to
# need buying, per the task's explicit instruction not to assume they
# must be bought.
STAPLE_ITEMS: frozenset[str] = frozenset(
    {
        "oil",
        "olive oil",
        "vegetable oil",
        "canola oil",
        "salt",
        "pepper",
        "black pepper",
        "flour",
        "sugar",
        "butter",
        "cumin",
        "paprika",
        "cinnamon",
        "oregano",
        "garlic powder",
        "onion powder",
        "chili powder",
        "cayenne pepper",
        "baking powder",
        "baking soda",
        "vanilla extract",
    }
)

_IMPORTANCE_RANK: dict[Importance, int] = {"critical": 0, "important": 1, "optional": 2}
_RANK_TO_IMPORTANCE: dict[int, Importance] = {
    rank: importance for importance, rank in _IMPORTANCE_RANK.items()
}


@dataclass
class _Aggregate:
    quantities: dict[str | None, float | None] = field(default_factory=dict)
    needed_for: list[str] = field(default_factory=list)
    importance_rank: int = _IMPORTANCE_RANK["optional"]


def _build_item(
    canonical: str, agg: _Aggregate, shelf_life_map: Mapping[str, ShelfLifeEntry]
) -> GroceryListItem:
    quantities = [
        GroceryQuantity(quantity=quantity, unit=unit)
        for unit, quantity in sorted(agg.quantities.items(), key=lambda pair: pair[0] or "")
    ]
    importance = _RANK_TO_IMPORTANCE[agg.importance_rank]

    category = resolve_category(canonical, shelf_life_map)
    section = CATEGORY_TO_SECTION[category]

    is_staple = canonical in STAPLE_ITEMS
    verify_note = (
        f"Commonly already on hand — verify you're actually out of {canonical} before buying more."
        if is_staple
        else None
    )

    return GroceryListItem(
        name=canonical,
        quantities=quantities,
        needed_for=agg.needed_for,
        importance=importance,
        section=section,
        is_staple=is_staple,
        verify_note=verify_note,
    )


async def create_grocery_list(
    missing_by_recipe: Sequence[RecipeMissingIngredients],
    pantry_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> GroceryList:
    """Aggregates every recipe's missing ingredients into one grocery
    list, persists it to grocery_lists with status 'active', and returns
    the structured result.

    Deduplication is on canonical name (normalize + resolve, same as
    every other pantry function): two recipes both missing "garlic"
    produce one line. Quantities combine only when their units match —
    2 cloves + 3 cloves becomes one (5, "clove") entry — because
    converting between genuinely different units (2 cloves + 1 head)
    isn't something this project has a conversion table for and
    shouldn't silently guess at; mismatched units stay as separate
    GroceryQuantity entries on the same line instead.
    """
    pantry_db = pantry_db or get_pantry_db()
    if synonym_map is None:
        synonym_map = await load_synonym_map(get_recipe_db())
    shelf_life_map = await load_shelf_life_map(pantry_db)

    aggregates: dict[str, _Aggregate] = {}
    for recipe in missing_by_recipe:
        for ingredient in recipe.missing_ingredients:
            canonical = resolve_canonical(normalize_ingredient(ingredient.name), synonym_map)
            agg = aggregates.setdefault(canonical, _Aggregate())

            if ingredient.quantity is None:
                agg.quantities.setdefault(ingredient.unit, None)
            else:
                current = agg.quantities.get(ingredient.unit) or 0.0
                agg.quantities[ingredient.unit] = current + ingredient.quantity

            if recipe.recipe_name not in agg.needed_for:
                agg.needed_for.append(recipe.recipe_name)
            agg.importance_rank = min(agg.importance_rank, _IMPORTANCE_RANK[ingredient.importance])

    items_by_section: dict[GrocerySection, list[GroceryListItem]] = {}
    for canonical, agg in aggregates.items():
        item = _build_item(canonical, agg, shelf_life_map)
        items_by_section.setdefault(item.section, []).append(item)

    sections = [
        GroceryListSection(section=section, items=sorted(items_by_section[section], key=lambda i: i.name))
        for section in SECTION_ORDER
        if section in items_by_section
    ]

    items_json = json.dumps([section.model_dump(mode="json") for section in sections])
    list_id = await pantry_db.execute(
        "INSERT INTO grocery_lists (status, items) VALUES ('active', ?)", (items_json,)
    )
    row = await pantry_db.fetch_one(
        "SELECT id, status, created_at FROM grocery_lists WHERE id = ?", (list_id,)
    )
    if row is None:
        raise RuntimeError(f"grocery_lists row {list_id} vanished immediately after insert")

    return GroceryList(
        id=row["id"],
        status=row["status"],
        created_at=parse_sqlite_timestamp(row["created_at"]),
        sections=sections,
    )


async def get_grocery_list(
    list_id: int | None = None, pantry_db: Database | None = None
) -> GroceryList | None:
    """Fetches one grocery list by id, or — if list_id is None — the
    most recently created list with status 'active'. Returns None if no
    matching list exists, rather than raising."""
    pantry_db = pantry_db or get_pantry_db()

    if list_id is not None:
        row = await pantry_db.fetch_one(
            "SELECT id, status, created_at, items FROM grocery_lists WHERE id = ?", (list_id,)
        )
    else:
        row = await pantry_db.fetch_one(
            "SELECT id, status, created_at, items FROM grocery_lists "
            "WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        )

    if row is None:
        return None

    sections = [GroceryListSection.model_validate(raw) for raw in json.loads(row["items"])]
    return GroceryList(
        id=row["id"],
        status=row["status"],
        created_at=parse_sqlite_timestamp(row["created_at"]),
        sections=sections,
    )


async def set_grocery_item_checked(
    list_id: int,
    item_name: str,
    checked: bool = True,
    pantry_db: Database | None = None,
    synonym_map: Mapping[str, str] | None = None,
) -> GroceryList | None:
    """Marks one item on one grocery list checked (or unchecked). Returns
    the updated list, or None if list_id doesn't exist. An item_name not
    actually on the list is a no-op — the list is returned unchanged."""
    pantry_db = pantry_db or get_pantry_db()
    if synonym_map is None:
        synonym_map = await load_synonym_map(get_recipe_db())

    grocery_list = await get_grocery_list(list_id=list_id, pantry_db=pantry_db)
    if grocery_list is None:
        return None

    canonical = resolve_canonical(normalize_ingredient(item_name), synonym_map)
    updated_sections = [
        GroceryListSection(
            section=section.section,
            items=[
                item.model_copy(update={"checked": checked}) if item.name == canonical else item
                for item in section.items
            ],
        )
        for section in grocery_list.sections
    ]

    items_json = json.dumps([section.model_dump(mode="json") for section in updated_sections])
    await pantry_db.execute("UPDATE grocery_lists SET items = ? WHERE id = ?", (items_json, list_id))

    return GroceryList(
        id=grocery_list.id,
        status=grocery_list.status,
        created_at=grocery_list.created_at,
        sections=updated_sections,
    )
